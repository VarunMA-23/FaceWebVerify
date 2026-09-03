/**
 * EvidenceChain Premium 3D Entry Experience
 * Vanilla Three.js — isolated from backend/pipeline logic.
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'evidencechain_intro_seen'; // legacy — no longer used to skip intro
  const DURATION = 5.0;

  const COLORS = {
    bg: 0xF8FAFC,
    primary: 0x38BDF8,
    primaryDark: 0x0284C7,
    text: 0x0F172A,
    success: 0x10B981,
    muted: 0x94A3B8,
  };

  const STAGES = [
    { start: 0.0, end: 1.0, id: 'face' },
    { start: 1.0, end: 2.0, id: 'web' },
    { start: 2.0, end: 2.8, id: 'verify' },
    { start: 2.8, end: 3.5, id: 'evidence' },
    { start: 3.5, end: 4.2, id: 'fingerprint' },
    { start: 4.2, end: 4.7, id: 'blockchain' },
    { start: 4.7, end: 5.0, id: 'final' },
  ];

  let overlay = null;
  let rafId = null;
  let renderer = null;
  let scene = null;
  let camera = null;
  let clock = null;
  let disposed = false;
  let forceReplay = false;
  let started = false;

  /* ── Abstract face point cloud (normalized -1..1) ── */
  function generateFacePoints(count) {
    const pts = [];
    const rng = mulberry32(42);

    // Head oval
    for (let i = 0; i < count * 0.55; i++) {
      const t = rng() * Math.PI * 2;
      const r = 0.55 + rng() * 0.12;
      const x = Math.cos(t) * r * 0.72;
      const y = Math.sin(t) * r * 0.95 + 0.05;
      const z = (rng() - 0.5) * 0.15;
      if (y > -0.35 && y < 0.95) pts.push(x, y, z);
    }
    // Left eye region
    for (let i = 0; i < count * 0.12; i++) {
      const t = rng() * Math.PI * 2;
      const r = rng() * 0.14;
      pts.push(-0.28 + Math.cos(t) * r, 0.28 + Math.sin(t) * r * 0.5, (rng() - 0.5) * 0.08);
    }
    // Right eye region
    for (let i = 0; i < count * 0.12; i++) {
      const t = rng() * Math.PI * 2;
      const r = rng() * 0.14;
      pts.push(0.28 + Math.cos(t) * r, 0.28 + Math.sin(t) * r * 0.5, (rng() - 0.5) * 0.08);
    }
    // Nose bridge
    for (let i = 0; i < count * 0.08; i++) {
      pts.push((rng() - 0.5) * 0.06, 0.05 + rng() * 0.2, (rng() - 0.5) * 0.06);
    }
    // Mouth arc
    for (let i = 0; i < count * 0.13; i++) {
      const t = Math.PI * 0.15 + rng() * Math.PI * 0.7;
      const r = 0.18 + rng() * 0.06;
      pts.push(Math.cos(t) * r, -0.22 + Math.sin(t) * r * 0.3, (rng() - 0.5) * 0.06);
    }

    return new Float32Array(pts.slice(0, count * 3));
  }

  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }
  function easeInOutCubic(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function stageProgress(elapsed, stage) {
    return clamp((elapsed - stage.start) / (stage.end - stage.start), 0, 1);
  }
  function currentStage(elapsed) {
    for (let i = STAGES.length - 1; i >= 0; i--) {
      if (elapsed >= STAGES[i].start) return STAGES[i];
    }
    return STAGES[0];
  }

  function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function webGLAvailable() {
    try {
      const c = document.createElement('canvas');
      return !!(window.WebGLRenderingContext && (c.getContext('webgl') || c.getContext('experimental-webgl')));
    } catch { return false; }
  }

  function isMobile() {
    return window.innerWidth < 768;
  }

  function particleCount() {
    if (isMobile()) return 180;
    if (window.innerWidth < 1024) return 320;
    return 480;
  }

  /* ── Canvas textures for labeled 3D blocks ── */
  function createCanvasTexture(THREE, width, height, drawFn) {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    drawFn(ctx, width, height);
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.minFilter = THREE.LinearFilter;
    tex.magFilter = THREE.LinearFilter;
    tex.userData = { canvas, ctx };
    return tex;
  }

  function redrawTexture(tex, drawFn) {
    if (!tex?.userData?.ctx) return;
    const { canvas, ctx } = tex.userData;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawFn(ctx, canvas.width, canvas.height);
    tex.needsUpdate = true;
  }

  function drawCardBg(ctx, w, h, accent) {
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#E0F2FE';
    ctx.fillRect(0, 0, w, 28);
    ctx.strokeStyle = accent || '#38BDF8';
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, w - 2, h - 2);
  }

  function drawSourceCard(ctx, w, h, label, subtitle, iconType) {
    drawCardBg(ctx, w, h);
    ctx.fillStyle = '#0284C7';
    ctx.font = 'bold 11px Inter, system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(label, 10, 19);
    ctx.fillStyle = '#64748B';
    ctx.font = '9px Inter, system-ui, sans-serif';
    ctx.fillText(subtitle, 10, h - 12);
    ctx.strokeStyle = '#38BDF8';
    ctx.lineWidth = 1.5;
    const cx = w - 22; const cy = h / 2 + 4;
    if (iconType === 'globe') {
      ctx.beginPath(); ctx.arc(cx, cy, 10, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.ellipse(cx, cy, 10, 4, 0, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(cx - 10, cy); ctx.lineTo(cx + 10, cy); ctx.stroke();
    } else if (iconType === 'social') {
      ctx.beginPath(); ctx.arc(cx - 5, cy, 5, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath(); ctx.arc(cx + 5, cy, 5, 0, Math.PI * 2); ctx.stroke();
    } else if (iconType === 'image') {
      ctx.strokeRect(cx - 10, cy - 7, 20, 14);
      ctx.beginPath(); ctx.moveTo(cx - 8, cy + 5); ctx.lineTo(cx - 2, cy - 2); ctx.lineTo(cx + 4, cy + 2); ctx.lineTo(cx + 8, cy - 4); ctx.stroke();
    } else if (iconType === 'link') {
      ctx.beginPath(); ctx.arc(cx - 4, cy, 5, Math.PI * 0.5, Math.PI * 1.5); ctx.stroke();
      ctx.beginPath(); ctx.arc(cx + 4, cy, 5, Math.PI * 1.5, Math.PI * 0.5); ctx.stroke();
    } else if (iconType === 'news') {
      ctx.fillStyle = '#38BDF8'; ctx.fillRect(cx - 9, cy - 6, 18, 3);
      ctx.fillStyle = '#94A3B8'; ctx.fillRect(cx - 9, cy - 1, 14, 2); ctx.fillRect(cx - 9, cy + 3, 16, 2);
    } else {
      ctx.strokeRect(cx - 9, cy - 7, 18, 14);
      ctx.beginPath(); ctx.moveTo(cx - 9, cy - 2); ctx.lineTo(cx + 9, cy - 2); ctx.stroke();
    }
  }

  function drawEvidencePanel(ctx, w, h) {
    ctx.fillStyle = 'rgba(224, 242, 254, 0.95)';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = '#38BDF8';
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, w - 2, h - 2);
    ctx.fillStyle = '#0284C7';
    ctx.font = 'bold 13px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('EVIDENCE', w / 2, 28);
    ctx.fillStyle = '#0F172A';
    ctx.font = '600 11px JetBrains Mono, monospace';
    ctx.fillText('FACE MATCH', w / 2, 52);
    ctx.fillStyle = '#0284C7';
    ctx.font = 'bold 16px JetBrains Mono, monospace';
    ctx.fillText('95.6%', w / 2, 72);
    ctx.fillStyle = '#64748B';
    ctx.font = '600 9px Inter, system-ui, sans-serif';
    ctx.fillText('EVIDENCE SCORE', w / 2, 92);
    ctx.fillStyle = '#0F172A';
    ctx.font = 'bold 14px JetBrains Mono, monospace';
    ctx.fillText('94 / 100', w / 2, 110);
  }

  function drawFingerprintPanel(ctx, w, h, hexLine) {
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#F1F5F9';
    ctx.fillRect(0, 0, w, 24);
    ctx.strokeStyle = '#0284C7';
    ctx.lineWidth = 2;
    ctx.strokeRect(1, 1, w - 2, h - 2);
    ctx.fillStyle = '#0284C7';
    ctx.font = 'bold 10px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.fillText('SHA-256', 10, 16);
    ctx.fillStyle = '#0F172A';
    ctx.font = '11px JetBrains Mono, monospace';
    ctx.textAlign = 'center';
    ctx.fillText(hexLine || 'a91f…7c42', w / 2, 44);
    ctx.fillStyle = '#64748B';
    ctx.font = '8px Inter, system-ui, sans-serif';
    ctx.fillText('EVIDENCE FINGERPRINT', w / 2, h - 10);
    for (let i = 0; i < 6; i++) {
      ctx.fillStyle = i % 2 ? '#E0F2FE' : '#F8FAFC';
      ctx.fillRect(8 + i * 38, 54, 34, 8);
    }
  }

  function drawChainBlock(ctx, w, h, data) {
    const { title, hash, isNew, verified } = data;
    ctx.fillStyle = isNew ? '#E0F2FE' : '#FFFFFF';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = verified ? '#10B981' : '#38BDF8';
    ctx.lineWidth = verified ? 2.5 : 1.5;
    ctx.strokeRect(1, 1, w - 2, h - 2);
    ctx.fillStyle = '#0284C7';
    ctx.font = 'bold 9px JetBrains Mono, monospace';
    ctx.textAlign = 'left';
    ctx.fillText(title, 8, 18);
    ctx.fillStyle = '#64748B';
    ctx.font = '8px JetBrains Mono, monospace';
    const lines = hash.match(/.{1,12}/g) || [hash];
    lines.slice(0, 3).forEach((line, i) => ctx.fillText(line, 8, 34 + i * 12));
    if (verified) {
      ctx.fillStyle = '#10B981';
      ctx.font = 'bold 9px Inter, system-ui, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText('✓ ATTEST', w - 8, h - 10);
    }
  }

  function addFacePlane(parent, THREE, texture, pw, ph, z) {
    const plane = new THREE.Mesh(
      new THREE.PlaneGeometry(pw, ph),
      new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false })
    );
    plane.position.z = z;
    parent.add(plane);
    return plane;
  }

  /* ── Label management ── */
  const labelEls = {};

  function createLabels(container) {
    const defs = [
      { id: 'face', pos: 'pos-top', html: '<div class="il-main">Face Detected</div><div class="il-sub">512-D Embedding</div>' },
      { id: 'web', pos: 'pos-top', html: '<div class="il-main">Discovering Public Sources</div><div class="il-sub">Reverse image search</div>' },
      { id: 'verify', pos: 'pos-top', html: '<div class="il-check"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg></div><div class="il-main">Source Verified</div><div class="il-stats"><span><b>3</b> sources</span><span><b>2</b> verified</span><span><b>1</b> best match</span></div>' },
      { id: 'evidence', pos: 'pos-bot', html: '<div class="il-main">Evidence</div><div class="il-stats"><span>Face match <b>95.6%</b></span><span>Evidence score <b>94/100</b></span></div>' },
      { id: 'fingerprint', pos: 'pos-bot', html: '<div class="il-main">Evidence Fingerprint</div><div class="il-mono" id="introHex">SHA-256</div>' },
      { id: 'blockchain', pos: 'pos-bot', html: '<div class="il-main">Blockchain Attested</div><div class="il-sub" style="color:#10B981">✓ Integrity record created</div>' },
    ];
    defs.forEach(d => {
      const el = document.createElement('div');
      el.className = 'intro-label ' + d.pos;
      el.dataset.stage = d.id;
      el.innerHTML = d.html;
      container.appendChild(el);
      labelEls[d.id] = el;
    });
  }

  function updateLabels(stageId, progress) {
    Object.keys(labelEls).forEach(id => {
      const el = labelEls[id];
      const show = id === stageId && progress > 0.08 && progress < 0.95;
      el.classList.toggle('visible', show);
    });
    const tags = overlay?.querySelectorAll('.intro-node-tag');
    if (tags) {
      tags.forEach(t => t.classList.remove('visible'));
    }
  }

  /* ── Three.js scene builder ── */
  function buildScene(THREE) {
    const count = particleCount();
    const faceTargets = generateFacePoints(count);
    const faceStarts = new Float32Array(count * 3);
    const rng = mulberry32(7);
    for (let i = 0; i < count * 3; i++) {
      faceStarts[i] = (rng() - 0.5) * 4;
    }

    const faceGeo = new THREE.BufferGeometry();
    faceGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    faceGeo.setAttribute('target', new THREE.BufferAttribute(faceTargets, 3));

    const faceMat = new THREE.PointsMaterial({
      color: COLORS.primary,
      size: isMobile() ? 0.035 : 0.028,
      transparent: true,
      opacity: 0.85,
      sizeAttenuation: true,
      depthWrite: false,
    });
    const facePoints = new THREE.Points(faceGeo, faceMat);
    scene.add(facePoints);

    // 512-D embedding badge (face analysis stage)
    const embedTex = createCanvasTexture(THREE, 180, 56, (ctx, w, h) => {
      ctx.fillStyle = 'rgba(255,255,255,0.95)';
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = '#38BDF8';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(1, 1, w - 2, h - 2);
      ctx.fillStyle = '#64748B';
      ctx.font = '600 9px Inter, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('FACE EMBEDDING', w / 2, 18);
      ctx.fillStyle = '#0284C7';
      ctx.font = 'bold 14px JetBrains Mono, monospace';
      ctx.fillText('512-D VECTOR', w / 2, 40);
    });
    const embedBadge = addFacePlane(scene, THREE, embedTex, 0.55, 0.17, 0);
    embedBadge.position.set(0, -0.95, 0);
    embedBadge.visible = false;

    // Wireframe lines connecting nearby face points (subset)
    const lineCount = isMobile() ? 40 : 80;
    const linePositions = new Float32Array(lineCount * 6);
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));
    const lineMat = new THREE.LineBasicMaterial({ color: COLORS.primary, transparent: true, opacity: 0.25 });
    const faceLines = new THREE.LineSegments(lineGeo, lineMat);
    scene.add(faceLines);

    // Web nodes — source cards with labels
    const sourceDefs = [
      { label: 'WEB', sub: 'Public page', icon: 'globe' },
      { label: 'SOCIAL', sub: 'Profile post', icon: 'social' },
      { label: 'IMAGE', sub: 'Reverse hit', icon: 'image' },
      { label: 'SOURCE', sub: 'Verified URL', icon: 'link' },
      { label: 'NEWS', sub: 'Media index', icon: 'news' },
      { label: 'FORUM', sub: 'Thread match', icon: 'archive' },
      { label: 'CDN', sub: 'Image mirror', icon: 'image' },
      { label: 'ARCHIVE', sub: 'Cached copy', icon: 'archive' },
    ];
    const nodeCount = isMobile() ? 6 : 8;
    const nodes = [];
    const nodeGroup = new THREE.Group();
    scene.add(nodeGroup);

    for (let i = 0; i < nodeCount; i++) {
      const def = sourceDefs[i % sourceDefs.length];
      const angle = (i / nodeCount) * Math.PI * 2 - Math.PI / 2;
      const radius = 2.2;
      const cardW = isMobile() ? 0.42 : 0.48;
      const cardH = isMobile() ? 0.28 : 0.32;
      const cardTex = createCanvasTexture(THREE, 192, 128, (ctx, w, h) =>
        drawSourceCard(ctx, w, h, def.label, def.sub, def.icon));
      const cardGroup = new THREE.Group();
      const geo = new THREE.BoxGeometry(cardW, cardH, 0.05);
      const mat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.95 });
      const mesh = new THREE.Mesh(geo, mat);
      const edgeGeo = new THREE.EdgesGeometry(geo);
      const edgeMat = new THREE.LineBasicMaterial({ color: COLORS.primary, transparent: true, opacity: 0.55 });
      mesh.add(new THREE.LineSegments(edgeGeo, edgeMat));
      addFacePlane(mesh, THREE, cardTex, cardW * 0.92, cardH * 0.88, 0.026);
      cardGroup.add(mesh);
      cardGroup.userData = {
        angle,
        radius,
        label: def.label,
        sub: def.sub,
        icon: def.icon,
        cardTex,
        verified: i < 3,
        index: i,
      };
      cardGroup.position.set(Math.cos(angle) * radius, Math.sin(angle) * radius * 0.6, 0);
      nodeGroup.add(cardGroup);
      nodes.push(cardGroup);
    }

    // Connection lines from center to nodes
    const connPositions = new Float32Array(nodeCount * 6);
    const connGeo = new THREE.BufferGeometry();
    connGeo.setAttribute('position', new THREE.BufferAttribute(connPositions, 3));
    const connMat = new THREE.LineBasicMaterial({ color: COLORS.primary, transparent: true, opacity: 0.35 });
    const connections = new THREE.LineSegments(connGeo, connMat);
    nodeGroup.add(connections);

    // Evidence core — icosahedron wireframe sphere
    const evidenceGeo = new THREE.IcosahedronGeometry(0.55, 2);
    const evidenceMat = new THREE.MeshBasicMaterial({
      color: COLORS.primary,
      wireframe: true,
      transparent: true,
      opacity: 0.5,
    });
    const evidenceCore = new THREE.Mesh(evidenceGeo, evidenceMat);
    const evidenceShell = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.58, 1),
      new THREE.MeshBasicMaterial({ color: COLORS.primary, transparent: true, opacity: 0.08, wireframe: false })
    );
    const evidenceGroup = new THREE.Group();
    evidenceGroup.add(evidenceCore);
    evidenceGroup.add(evidenceShell);
    const evidenceTex = createCanvasTexture(THREE, 220, 140, drawEvidencePanel);
    const evidencePanel = addFacePlane(evidenceGroup, THREE, evidenceTex, 0.72, 0.46, 0.01);
    evidencePanel.material.opacity = 0.92;
    evidenceGroup.visible = false;
    scene.add(evidenceGroup);

    // Fingerprint block with SHA-256 face
    const fpGeo = new THREE.BoxGeometry(1.05, 0.42, 0.14);
    const fpTex = createCanvasTexture(THREE, 256, 96, (ctx, w, h) => drawFingerprintPanel(ctx, w, h, 'a91f…7c42'));
    const fpMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.98 });
    const fingerprint = new THREE.Mesh(fpGeo, fpMat);
    addFacePlane(fingerprint, THREE, fpTex, 1.0, 0.38, 0.071);
    fingerprint.add(new THREE.LineSegments(
      new THREE.EdgesGeometry(fpGeo),
      new THREE.LineBasicMaterial({ color: COLORS.primaryDark })
    ));
    fingerprint.userData.fpTexture = fpTex;
    fingerprint.visible = false;
    scene.add(fingerprint);

    // Blockchain blocks with hash content
    const chainGroup = new THREE.Group();
    const chainBlocks = [];
    const blockCount = 5;
    const blockDefs = [
      { title: 'BLOCK #142', hash: 'genesis…a4f2' },
      { title: 'BLOCK #143', hash: '7c42e1…9b0d' },
      { title: 'BLOCK #144', hash: 'd18e55…3f7a' },
      { title: 'BLOCK #145', hash: '2a91bc…e881' },
      { title: 'BLOCK #146', hash: '8F91A7…1CA71C', isNew: true },
    ];
    for (let i = 0; i < blockCount; i++) {
      const def = blockDefs[i];
      const bGeo = new THREE.BoxGeometry(0.58, 0.44, 0.2);
      const bMat = new THREE.MeshBasicMaterial({
        color: def.isNew ? 0xE0F2FE : 0xffffff,
        transparent: true,
        opacity: 0.95,
      });
      const block = new THREE.Mesh(bGeo, bMat);
      const bTex = createCanvasTexture(THREE, 160, 120, (ctx, w, h) =>
        drawChainBlock(ctx, w, h, { ...def, verified: false }));
      addFacePlane(block, THREE, bTex, 0.52, 0.38, 0.101);
      block.add(new THREE.LineSegments(
        new THREE.EdgesGeometry(bGeo),
        new THREE.LineBasicMaterial({ color: COLORS.primary, transparent: true, opacity: 0.5 })
      ));
      block.userData.blockTexture = bTex;
      block.userData.blockDef = def;
      block.position.x = (i - (blockCount - 1) / 2) * 0.72;
      chainGroup.add(block);
      chainBlocks.push(block);
    }
    // Chain links
    const linkPositions = new Float32Array((blockCount - 1) * 6);
    const linkGeo = new THREE.BufferGeometry();
    linkGeo.setAttribute('position', new THREE.BufferAttribute(linkPositions, 3));
    const links = new THREE.LineSegments(linkGeo, new THREE.LineBasicMaterial({ color: COLORS.primary, opacity: 0.4, transparent: true }));
    chainGroup.add(links);
    chainGroup.visible = false;
    scene.add(chainGroup);

    // Collapse group for final transition
    const collapseGroup = new THREE.Group();
    collapseGroup.add(facePoints);
    collapseGroup.add(faceLines);
    collapseGroup.add(embedBadge);
    collapseGroup.add(nodeGroup);
    collapseGroup.add(evidenceGroup);
    collapseGroup.add(fingerprint);
    collapseGroup.add(chainGroup);
    scene.add(collapseGroup);

    return {
      facePoints, embedBadge, faceGeo, faceStarts, faceTargets, faceLines, lineGeo, lineCount,
      nodeGroup, nodes, connections, connGeo, connPositions,
      evidenceGroup, evidenceCore, fingerprint, chainGroup, chainBlocks, links, linkPositions, blockCount,
      collapseGroup, count,
    };
  }

  function updateLines(lineGeo, positions, faceGeo, lineCount) {
    const pos = faceGeo.attributes.position.array;
    const arr = lineGeo.attributes.position.array;
    const step = Math.floor(positions.length / 3 / lineCount) || 1;
    for (let i = 0; i < lineCount; i++) {
      const a = i * step * 3;
      const b = ((i * step + 3) % (positions.length / 3)) * 3;
      arr[i * 6] = pos[a]; arr[i * 6 + 1] = pos[a + 1]; arr[i * 6 + 2] = pos[a + 2];
      arr[i * 6 + 3] = pos[b]; arr[i * 6 + 4] = pos[b + 1]; arr[i * 6 + 5] = pos[b + 2];
    }
    lineGeo.attributes.position.needsUpdate = true;
  }

  function updateConnections(connPositions, nodes, opacity) {
    for (let i = 0; i < nodes.length; i++) {
      connPositions[i * 6] = 0; connPositions[i * 6 + 1] = 0; connPositions[i * 6 + 2] = 0;
      connPositions[i * 6 + 3] = nodes[i].position.x;
      connPositions[i * 6 + 4] = nodes[i].position.y;
      connPositions[i * 6 + 5] = nodes[i].position.z;
    }
    return opacity;
  }

  function updateChainLinks(linkPositions, blocks) {
    for (let i = 0; i < blocks.length - 1; i++) {
      const a = blocks[i].position;
      const b = blocks[i + 1].position;
      linkPositions[i * 6] = a.x + 0.29; linkPositions[i * 6 + 1] = a.y; linkPositions[i * 6 + 2] = a.z;
      linkPositions[i * 6 + 3] = b.x - 0.29; linkPositions[i * 6 + 4] = b.y; linkPositions[i * 6 + 5] = b.z;
    }
  }

  const HEX_CHARS = '0123456789abcdef';
  const HEX_FINAL = '8F91A71C';

  function randomHex(len) {
    let s = '';
    for (let i = 0; i < len; i++) s += HEX_CHARS[Math.floor(Math.random() * 16)];
    return s;
  }

  function nodeMesh(node) {
    return node.children[0];
  }

  function setNodeCardVerified(node, verified) {
    if (!node.userData.cardTex || node.userData._verifiedDrawn === verified) return;
    node.userData._verifiedDrawn = verified;
    redrawTexture(node.userData.cardTex, (ctx, w, h) => {
      drawSourceCard(ctx, w, h, node.userData.label, verified ? '✓ Verified source' : node.userData.sub, node.userData.icon);
      if (verified) {
        ctx.fillStyle = '#10B981';
        ctx.font = 'bold 14px Inter, system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText('✓', w - 10, 22);
        ctx.strokeStyle = '#10B981';
        ctx.lineWidth = 2;
        ctx.strokeRect(2, 2, w - 4, h - 4);
      }
    });
  }

  function animateFrame(elapsed, objects) {
    const stage = currentStage(elapsed);
    const prog = stageProgress(elapsed, stage);
    const {
      faceGeo, faceStarts, faceTargets, faceLines, lineGeo, lineCount,
      nodeGroup, nodes, connections, connGeo, connPositions,
      evidenceGroup, evidenceCore, fingerprint, chainGroup, chainBlocks, links, linkPositions, blockCount,
      collapseGroup, count, facePoints, embedBadge,
    } = objects;

    const pos = faceGeo.attributes.position.array;
    let globalScale = 1;
    let globalOpacity = 1;

    // ── Stage: Face ──
    if (stage.id === 'face') {
      const t = easeOutCubic(prog);
      for (let i = 0; i < count * 3; i++) {
        pos[i] = lerp(faceStarts[i], faceTargets[i], t);
      }
      faceGeo.attributes.position.needsUpdate = true;
      updateLines(lineGeo, pos, faceGeo, lineCount);
      faceLines.material.opacity = t * 0.3;
      nodeGroup.visible = false;
      evidenceGroup.visible = false;
      fingerprint.visible = false;
      chainGroup.visible = false;
      facePoints.visible = true;
      embedBadge.visible = t > 0.35;
      embedBadge.material.opacity = clamp((t - 0.35) / 0.4, 0, 1);
      collapseGroup.scale.setScalar(1);
      camera.position.z = lerp(4.5, 3.8, t);
    }

    // ── Stage: Web discovery ──
    if (stage.id === 'web') {
      const t = easeInOutCubic(prog);
      for (let i = 0; i < count * 3; i++) {
        const expand = 1 + t * 1.8;
        pos[i] = faceTargets[i] * expand + (faceTargets[i] * 0.3 * Math.sin(elapsed * 2 + i));
      }
      faceGeo.attributes.position.needsUpdate = true;
      facePoints.material.opacity = lerp(0.85, 0.25, t);
      faceLines.material.opacity = 0.1;
      embedBadge.visible = t < 0.4;
      if (embedBadge.visible) embedBadge.material.opacity = lerp(1, 0, t / 0.4);

      nodeGroup.visible = true;
      nodes.forEach((node, i) => {
        const np = easeOutCubic(clamp(t - i * 0.05, 0, 1));
        const r = node.userData.radius * np;
        node.position.x = Math.cos(node.userData.angle) * r;
        node.position.y = Math.sin(node.userData.angle) * r * 0.6;
        const mesh = nodeMesh(node);
        mesh.material.opacity = np * 0.95;
        node.scale.setScalar(0.5 + np * 0.5);
      });
      updateConnections(connPositions, nodes, t);
      connGeo.attributes.position.needsUpdate = true;
      connections.material.opacity = t * 0.4;
      evidenceGroup.visible = false;
      fingerprint.visible = false;
      chainGroup.visible = false;
    }

    // ── Stage: Verification ──
    if (stage.id === 'verify') {
      const t = easeInOutCubic(prog);
      facePoints.visible = t < 0.5;
      facePoints.material.opacity = lerp(0.2, 0, t * 2);
      nodeGroup.visible = true;

      nodes.forEach((node) => {
        const mesh = nodeMesh(node);
        if (node.userData.verified) {
          const target = { x: node.userData.index * 0.45 - 0.45, y: 0, z: 0 };
          node.position.x = lerp(node.position.x, target.x, t * 0.08 + 0.02);
          node.position.y = lerp(node.position.y, target.y, t * 0.08 + 0.02);
          setNodeCardVerified(node, t > 0.45);
          mesh.material.color.setHex(t > 0.5 ? 0xf0fdf4 : 0xffffff);
        } else {
          mesh.material.opacity = lerp(0.95, 0, t);
          node.scale.setScalar(lerp(1, 0.3, t));
        }
      });
      connections.material.opacity = lerp(0.3, 0.05, t);
      evidenceGroup.visible = false;
      fingerprint.visible = false;
      chainGroup.visible = false;
    }

    // ── Stage: Evidence ──
    if (stage.id === 'evidence') {
      const t = easeOutCubic(prog);
      nodeGroup.visible = true;
      nodes.forEach((node) => {
        const mesh = nodeMesh(node);
        mesh.material.opacity = lerp(mesh.material.opacity, 0, t * 0.15);
        node.position.multiplyScalar(1 - t * 0.02);
      });
      connections.material.opacity = lerp(0.05, 0, t);

      evidenceGroup.visible = true;
      evidenceGroup.scale.setScalar(t * 1.2);
      evidenceCore.rotation.y = elapsed * 0.4;
      evidenceCore.rotation.x = Math.sin(elapsed) * 0.15;
      evidenceGroup.position.set(0, 0, 0);

      fingerprint.visible = false;
      chainGroup.visible = false;
      facePoints.visible = false;
    }

    // ── Stage: Fingerprint ──
    if (stage.id === 'fingerprint') {
      const t = easeInOutCubic(prog);
      evidenceGroup.visible = true;
      evidenceGroup.scale.setScalar(lerp(1.2, 0.15, t));
      evidenceGroup.position.y = lerp(0, 0, t);

      fingerprint.visible = t > 0.3;
      if (fingerprint.visible) {
        const ft = clamp((t - 0.3) / 0.7, 0, 1);
        fingerprint.scale.setScalar(0.3 + ft * 0.7);
        fingerprint.position.set(0, lerp(0.3, 0, ft), 0);
        fingerprint.rotation.y = ft * 0.3;
      }
      nodeGroup.visible = false;
      chainGroup.visible = false;

      const hexDisplay = t < 0.85
        ? randomHex(4) + '…' + randomHex(4)
        : HEX_FINAL.slice(0, 4) + '…' + HEX_FINAL.slice(4);
      if (fingerprint.userData.fpTexture) {
        redrawTexture(fingerprint.userData.fpTexture, (ctx, w, h) =>
          drawFingerprintPanel(ctx, w, h, hexDisplay));
      }

      const hexEl = document.getElementById('introHex');
      if (hexEl) {
        if (t < 0.85) {
          hexEl.textContent = 'SHA-256  ' + randomHex(4) + '…' + randomHex(4);
        } else {
          const settle = easeOutCubic((t - 0.85) / 0.15);
          hexEl.textContent = 'SHA-256  ' + HEX_FINAL.slice(0, 4) + '…' + HEX_FINAL.slice(4);
          hexEl.style.opacity = settle;
        }
      }
    }

    // ── Stage: Blockchain ──
    if (stage.id === 'blockchain') {
      const t = easeOutCubic(prog);
      fingerprint.visible = true;
      fingerprint.position.y = lerp(0, -0.5, t);
      fingerprint.material.opacity = lerp(0.95, 0, t);
      evidenceGroup.visible = false;
      nodeGroup.visible = false;

      chainGroup.visible = t > 0.15;
      if (chainGroup.visible) {
        const ct = clamp((t - 0.15) / 0.85, 0, 1);
        chainGroup.scale.setScalar(0.6 + ct * 0.4);
        chainBlocks.forEach((block, i) => {
          const bp = easeOutCubic(clamp(ct * 1.3 - i * 0.12, 0, 1));
          block.scale.setScalar(bp);
          block.position.y = lerp(0.5, 0, bp);
          if (i === blockCount - 1) {
            block.material.color.setHex(ct > 0.7 ? 0xecfdf5 : 0xE0F2FE);
            const verified = ct > 0.75;
            if (block.userData.blockTexture && block.userData._attested !== verified) {
              block.userData._attested = verified;
              redrawTexture(block.userData.blockTexture, (ctx, w, h) =>
                drawChainBlock(ctx, w, h, { ...block.userData.blockDef, verified }));
            }
          }
        });
        updateChainLinks(linkPositions, chainBlocks);
        links.geometry.attributes.position.needsUpdate = true;
      }
    }

    // ── Stage: Final collapse ──
    if (stage.id === 'final') {
      const t = easeInOutCubic(prog);
      globalScale = lerp(1, 0.01, t);
      globalOpacity = lerp(1, 0, t);
      collapseGroup.scale.setScalar(globalScale);
      chainGroup.visible = t < 0.6;
      if (t > 0.6) {
        chainGroup.visible = false;
        facePoints.visible = false;
      }

      const finalEl = overlay.querySelector('.intro-final');
      if (finalEl) finalEl.classList.toggle('visible', t > 0.35);
    }

    updateLabels(stage.id, prog);

    // Subtle camera drift
    if (stage.id !== 'final') {
      camera.position.x = Math.sin(elapsed * 0.3) * 0.08;
      camera.position.y = Math.cos(elapsed * 0.25) * 0.05;
      camera.lookAt(0, 0, 0);
    }

    renderer.setClearColor(COLORS.bg, 1);
  }

  function disposeThree(objects) {
    if (!objects) return;
    const disposeObj = (obj) => {
      if (!obj) return;
      obj.traverse?.((child) => {
        if (child.geometry) child.geometry.dispose();
        if (child.material) {
          if (Array.isArray(child.material)) child.material.forEach(m => m.dispose());
          else child.material.dispose();
        }
        if (child.material?.map) child.material.map.dispose();
      });
    };
    disposeObj(objects.collapseGroup);
  }

  function finishIntro() {
    if (disposed) return;
    disposed = true;
    document.removeEventListener('keydown', onKeyDown);
    if (rafId) cancelAnimationFrame(rafId);
    disposeThree(window.__introObjects);
    window.__introObjects = null;

    if (renderer) {
      renderer.dispose();
      renderer.forceContextLoss?.();
      renderer.domElement = null;
      renderer = null;
    }

    document.body.classList.remove('intro-active');

    if (overlay) {
      overlay.classList.add('intro-out');
      setTimeout(() => {
        overlay.classList.add('hidden-immediate');
        overlay.remove();
        overlay = null;
      }, 650);
    }
  }

  function runFallback() {
    const ui = overlay.querySelector('.intro-ui');
    ui.innerHTML = `
      <button class="intro-skip" id="introSkipBtn" type="button">SKIP INTRO →</button>
      <div class="intro-fallback">
        <div class="if-logo">EvidenceChain</div>
        <div class="if-tag">DISCOVER · VERIFY · ATTEST</div>
        <div class="intro-fallback-steps">
          <span>Face</span> → Web discovery → Source verification → Evidence → SHA-256 → Blockchain attestation
        </div>
      </div>`;
    ui.querySelector('#introSkipBtn').addEventListener('click', finishIntro);
    setTimeout(finishIntro, 2200);
  }

  function runThreeIntro(THREE) {
    const canvas = overlay.querySelector('#introCanvas');
    const uiContainer = overlay.querySelector('.intro-ui');
    createLabels(uiContainer);

    // Final logo element
    const finalEl = document.createElement('div');
    finalEl.className = 'intro-final';
    finalEl.innerHTML = `
      <div class="if-logo">
        <div class="if-icon"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg></div>
        EvidenceChain
      </div>
      <div class="if-tag">DISCOVER · VERIFY · ATTEST</div>`;
    uiContainer.appendChild(finalEl);

    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight, false);

    scene = new THREE.Scene();
    scene.fog = new THREE.Fog(COLORS.bg, 4, 12);

    camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 50);
    camera.position.set(0, 0, 3.8);

    const ambient = new THREE.AmbientLight(0xffffff, 0.9);
    scene.add(ambient);
    const dir = new THREE.DirectionalLight(COLORS.primary, 0.4);
    dir.position.set(2, 3, 4);
    scene.add(dir);

    const objects = buildScene(THREE);
    window.__introObjects = objects;
    clock = { start: performance.now() };

    function onResize() {
      if (!renderer || !camera) return;
      const w = window.innerWidth;
      const h = window.innerHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    }
    window.addEventListener('resize', onResize);

    function loop(now) {
      if (disposed) return;
      const elapsed = (now - clock.start) / 1000;
      animateFrame(elapsed, objects);
      renderer.render(scene, camera);

      if (elapsed >= DURATION) {
        window.removeEventListener('resize', onResize);
        finishIntro();
        return;
      }
      rafId = requestAnimationFrame(loop);
    }
    rafId = requestAnimationFrame(loop);
  }

  function createOverlay() {
    overlay = document.createElement('div');
    overlay.id = 'introOverlay';
    overlay.className = 'intro-overlay';
    overlay.innerHTML = `
      <canvas id="introCanvas" aria-hidden="true"></canvas>
      <div class="intro-ui">
        <button class="intro-skip" id="introSkipBtn" type="button">SKIP INTRO →</button>
      </div>`;
    document.body.prepend(overlay);

    overlay.querySelector('#introSkipBtn').addEventListener('click', finishIntro);
    document.addEventListener('keydown', onKeyDown);
  }

  function onKeyDown(e) {
    if (e.key === 'Escape' && overlay && !disposed) finishIntro();
  }

  function shouldShowIntro() {
    if (forceReplay) return true;
    try {
      const params = new URLSearchParams(window.location.search);
      // Allow skipping via URL for dev/testing: /?nointro=1
      if (params.get('nointro') === '1') return false;
      // Always play intro on page load / reload of /
      return true;
    } catch { return true; }
  }

  function loadThree() {
    return new Promise((resolve, reject) => {
      if (window.THREE) { resolve(window.THREE); return; }
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js';
      s.crossOrigin = 'anonymous';
      s.onload = () => {
        if (window.THREE) resolve(window.THREE);
        else reject(new Error('THREE global missing'));
      };
      s.onerror = () => reject(new Error('Three.js failed to load'));
      document.head.appendChild(s);
    });
  }

  function init(options = {}) {
    forceReplay = !!options.replay;
    if (started && !options.replay) return Promise.resolve(false);
    if (!shouldShowIntro()) return Promise.resolve(false);

    started = true;
    disposed = false;
    document.body.classList.add('intro-active');
    createOverlay();

    if (prefersReducedMotion() || !webGLAvailable()) {
      runFallback();
      return Promise.resolve(true);
    }

    return loadThree()
      .then((THREE) => { runThreeIntro(THREE); return true; })
      .catch(() => { runFallback(); return true; });
  }

  function replay() {
    forceReplay = true;
    disposed = false;
    started = false;
    if (overlay) overlay.remove();
    overlay = null;
    document.body.classList.remove('intro-active');
    return init({ replay: true });
  }

  window.EvidenceChainIntro = { init, replay, finish: finishIntro };

  function bootIntro() {
    init().catch(() => runFallback());
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootIntro);
  } else {
    bootIntro();
  }
})();
