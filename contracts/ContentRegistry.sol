// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ContentRegistry
/// @notice Immutable, tamper-evident registry of SHA-256 content hashes.
contract ContentRegistry {
    mapping(bytes32 => bool) public registered;
    mapping(bytes32 => uint256) public registeredAt;

    event ContentRegistered(bytes32 indexed contentHash, address indexed registrar, uint256 timestamp);

    /// @notice Register a content hash on-chain.
    /// @param contentHash SHA-256 digest of the canonical content record.
    function register(bytes32 contentHash) external {
        require(contentHash != bytes32(0), "ContentRegistry: empty hash");
        registered[contentHash] = true;
        registeredAt[contentHash] = block.timestamp;
        emit ContentRegistered(contentHash, msg.sender, block.timestamp);
    }

    /// @notice Verify whether a content hash exists on-chain.
    /// @param contentHash SHA-256 digest to check.
    /// @return true if the hash was previously registered.
    function verify(bytes32 contentHash) external view returns (bool) {
        return registered[contentHash];
    }
}