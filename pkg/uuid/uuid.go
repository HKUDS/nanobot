package uuid

import (
	"crypto/rand"
	"encoding/hex"
	"io"

	"github.com/google/uuid"
)

func String() string {
	var uuid [16]byte
	_, err := io.ReadFull(rand.Reader, uuid[:])
	if err != nil {
		panic("failed to generate UUID: " + err.Error())
	}
	uuid[6] = (uuid[6] & 0x0f) | 0x40 // Version 4
	uuid[8] = (uuid[8] & 0x3f) | 0x80 // Variant is 10

	var dst [36]byte
	hex.Encode(dst[:], uuid[:4])
	dst[8] = '-'
	hex.Encode(dst[9:13], uuid[4:6])
	dst[13] = '-'
	hex.Encode(dst[14:18], uuid[6:8])
	dst[18] = '-'
	hex.Encode(dst[19:23], uuid[8:10])
	dst[23] = '-'
	hex.Encode(dst[24:], uuid[10:])

	return string(dst[:])
}

func ValidUUID(s string) bool {
	_, err := uuid.Parse(s)
	return err == nil
}
