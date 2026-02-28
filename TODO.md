# XMPP Channel TODO

## Future Enhancements

### File Transfer Support
- Implement XEP-0065 (SOCKS5 Bytestreams) for direct file transfers
- Implement XEP-0363 (HTTP File Upload) for server-mediated transfers
- Add configuration options for max file size and allowed file types
- Handle media downloads to `~/.nanobot/media/` following the pattern used by other channels

### OMEMO Encryption
- Implement XEP-0384 (OMEMO Encryption) for end-to-end encryption
- Add device management and trust verification
- Include OMEMO trust settings in configuration schema
- Handle encrypted group chats (MUC) with OMEMO
