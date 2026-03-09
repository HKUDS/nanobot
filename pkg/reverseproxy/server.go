package reverseproxy

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net"
	"time"

	"log/slog"
)

// TLSServer represents a TLS server with mTLS authentication
type TLSServer struct {
	caCert     *x509.Certificate
	caKey      *ecdsa.PrivateKey
	serverCert *x509.Certificate
	serverKey  *ecdsa.PrivateKey
	config     *tls.Config
	targetPort int
}

// NewTLSServer creates a new TLS server with generated certificates
func NewTLSServer(targetPort int) (*TLSServer, error) {
	// Generate CA key and certificate
	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("failed to generate CA key: %v", err)
	}

	caTemplate := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject: pkix.Name{
			Organization: []string{"Nanobot Temp CA"},
		},
		NotBefore:             time.Now(),
		NotAfter:              time.Now().Add(24 * time.Hour),
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
		BasicConstraintsValid: true,
		IsCA:                  true,
	}

	caCertDER, err := x509.CreateCertificate(rand.Reader, caTemplate, caTemplate, &caKey.PublicKey, caKey)
	if err != nil {
		return nil, fmt.Errorf("failed to create CA certificate: %v", err)
	}

	caCert, err := x509.ParseCertificate(caCertDER)
	if err != nil {
		return nil, fmt.Errorf("failed to parse CA certificate: %v", err)
	}

	// Generate server key and certificate
	serverKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("failed to generate server key: %v", err)
	}

	serverTemplate := &x509.Certificate{
		SerialNumber: big.NewInt(2),
		Subject: pkix.Name{
			Organization: []string{"Test Server"},
		},
		NotBefore:   time.Now(),
		NotAfter:    time.Now().Add(24 * time.Hour),
		KeyUsage:    x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		IPAddresses: []net.IP{net.ParseIP("127.0.0.1")},
	}

	serverCertDER, err := x509.CreateCertificate(rand.Reader, serverTemplate, caCert, &serverKey.PublicKey, caKey)
	if err != nil {
		return nil, fmt.Errorf("failed to create server certificate: %v", err)
	}

	serverCert, err := x509.ParseCertificate(serverCertDER)
	if err != nil {
		return nil, fmt.Errorf("failed to parse server certificate: %v", err)
	}

	// Create TLS config
	config := &tls.Config{
		Certificates: []tls.Certificate{
			{
				Certificate: [][]byte{serverCertDER},
				PrivateKey:  serverKey,
				Leaf:        serverCert,
			},
		},
		ClientCAs:  x509.NewCertPool(),
		ClientAuth: tls.RequireAndVerifyClientCert,
		MinVersion: tls.VersionTLS12,
	}

	config.ClientCAs.AddCert(caCert)

	return &TLSServer{
		caCert:     caCert,
		caKey:      caKey,
		serverCert: serverCert,
		serverKey:  serverKey,
		config:     config,
		targetPort: targetPort,
	}, nil
}

// GetCACertPEM returns the CA certificate in PEM format
func (s *TLSServer) GetCACertPEM() ([]byte, error) {
	return pem.EncodeToMemory(&pem.Block{
		Type:  "CERTIFICATE",
		Bytes: s.caCert.Raw,
	}), nil
}

// GenerateClientCert generates a client certificate signed by the CA
func (s *TLSServer) GenerateClientCert() ([]byte, []byte, error) {
	clientKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to generate client key: %v", err)
	}

	clientTemplate := &x509.Certificate{
		SerialNumber: big.NewInt(3),
		Subject: pkix.Name{
			Organization: []string{"Nanobot Client"},
		},
		NotBefore:   time.Now(),
		NotAfter:    time.Now().Add(24 * time.Hour),
		KeyUsage:    x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}

	clientCertDER, err := x509.CreateCertificate(rand.Reader, clientTemplate, s.caCert, &clientKey.PublicKey, s.caKey)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to create client certificate: %v", err)
	}

	clientCertPEM := pem.EncodeToMemory(&pem.Block{
		Type:  "CERTIFICATE",
		Bytes: clientCertDER,
	})

	clientKeyBytes, err := x509.MarshalECPrivateKey(clientKey)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to marshal client key: %v", err)
	}

	clientKeyPEM := pem.EncodeToMemory(&pem.Block{
		Type:  "EC PRIVATE KEY",
		Bytes: clientKeyBytes,
	})

	return clientCertPEM, clientKeyPEM, nil
}

// Start starts the TLS server on a random port and returns the allocated port
func (s *TLSServer) Start(ctx context.Context) (int, error) {
	listener, err := tls.Listen("tcp4", ":0", s.config)
	if err != nil {
		return 0, fmt.Errorf("failed to create listener: %v", err)
	}

	context.AfterFunc(ctx, func() {
		_ = listener.Close()
	})

	// Get the actual port that was allocated
	addr := listener.Addr().(*net.TCPAddr)
	port := addr.Port

	go func() {
		defer listener.Close()
		for {
			conn, err := listener.Accept()
			if err != nil {
				select {
				case <-ctx.Done():
					return
				default:
				}
				slog.Error("failed to accept connection", "error", err)
				continue
			}

			go s.handleConnection(ctx, conn)
		}
	}()

	return port, nil
}

func (s *TLSServer) handleConnection(ctx context.Context, clientConn net.Conn) {
	defer func() {
		_ = clientConn.Close()
	}()

	// Connect to the target server
	targetAddr := fmt.Sprintf("localhost:%d", s.targetPort)
	targetConn, err := net.Dial("tcp", targetAddr)
	if err != nil {
		slog.Error("failed to connect to target", "target_addr", targetAddr, "error", err)
		return
	}
	defer func() {
		_ = targetConn.Close()
	}()

	// Create channels to wait for either connection to close
	clientClosed := make(chan struct{})
	targetClosed := make(chan struct{})

	// Copy data from client to target
	go func() {
		_, err := io.Copy(targetConn, clientConn)
		if err != nil && !errors.Is(err, io.EOF) {
			slog.Error("error copying from client to target", "error", err)
		}
		close(clientClosed)
	}()

	// Copy data from target to client
	go func() {
		_, err := io.Copy(clientConn, targetConn)
		if err != nil && !errors.Is(err, io.EOF) {
			slog.Error("error copying from target to client", "error", err)
		}
		close(targetClosed)
	}()

	// Wait for either connection to close
	select {
	case <-clientClosed:
		_ = targetConn.Close()
	case <-targetClosed:
		_ = clientConn.Close()
	}
}
