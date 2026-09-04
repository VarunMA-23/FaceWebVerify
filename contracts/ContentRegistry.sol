// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ContentRegistry
/// @notice Immutable, tamper-evident registry of SHA-256 content hashes.
contract ContentRegistry {
    enum EvidenceStatus {
        Active,
        Revoked
    }

    struct Evidence {
        bytes32 contentHash;
        address issuer;
        uint256 timestamp;
        EvidenceStatus status;
    }

    mapping(bytes32 => bool) public registered;
    mapping(bytes32 => uint256) public registeredAt;
    mapping(bytes32 => bytes32) public evidenceContentHash;
    mapping(bytes32 => Evidence) public evidence;

    event ContentRegistered(bytes32 indexed contentHash, address indexed registrar, uint256 timestamp);
    event EvidenceRegistered(
        bytes32 indexed evidenceId,
        bytes32 indexed contentHash,
        address indexed registrar,
        uint256 timestamp
    );
    event EvidenceRevoked(
        bytes32 indexed evidenceId,
        address indexed revoker,
        uint256 timestamp
    );

    /// @notice Register a content hash on-chain.
    /// @param contentHash SHA-256 digest of the canonical content record.
    function register(bytes32 contentHash) external {
        require(contentHash != bytes32(0), "ContentRegistry: empty hash");
        require(!registered[contentHash], "ContentRegistry: hash already registered");
        registered[contentHash] = true;
        registeredAt[contentHash] = block.timestamp;
        emit ContentRegistered(contentHash, msg.sender, block.timestamp);
    }

    /// @notice Associate an evidence ID with a content hash.
    /// @param evidenceId Identifier for the evidence record.
    /// @param contentHash SHA-256 digest of the canonical content record.
    function registerEvidence(bytes32 evidenceId, bytes32 contentHash) external {
        require(evidenceId != bytes32(0), "ContentRegistry: empty evidence ID");
        require(contentHash != bytes32(0), "ContentRegistry: empty hash");
        require(
            evidenceContentHash[evidenceId] == bytes32(0),
            "ContentRegistry: evidence already registered"
        );
        evidenceContentHash[evidenceId] = contentHash;
        evidence[evidenceId] = Evidence(
            contentHash,
            msg.sender,
            block.timestamp,
            EvidenceStatus.Active
        );
        emit EvidenceRegistered(evidenceId, contentHash, msg.sender, block.timestamp);
    }

    function revokeEvidence(bytes32 evidenceId) external {
        require(
            evidence[evidenceId].contentHash != bytes32(0),
            "ContentRegistry: evidence not registered"
        );
        require(evidence[evidenceId].issuer == msg.sender, "ContentRegistry: unauthorized");
        require(
            evidence[evidenceId].status != EvidenceStatus.Revoked,
            "ContentRegistry: evidence already revoked"
        );
        evidence[evidenceId].status = EvidenceStatus.Revoked;
        emit EvidenceRevoked(evidenceId, msg.sender, block.timestamp);
    }

    function getEvidence(bytes32 evidenceId)
        external
        view
        returns (
            bytes32 contentHash,
            address issuer,
            uint256 timestamp,
            EvidenceStatus status
        )
    {
        Evidence memory record = evidence[evidenceId];
        return (record.contentHash, record.issuer, record.timestamp, record.status);
    }

    /// @notice Verify whether a content hash exists on-chain.
    /// @param contentHash SHA-256 digest to check.
    /// @return true if the hash was previously registered.
    function verify(bytes32 contentHash) external view returns (bool) {
        return registered[contentHash];
    }
}