package reverseproxy

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"net"
	"os/exec"
	"strings"

	"log/slog"
)

// TLSClient represents a non-TLS server that proxies connections to a TLS server
type TLSClient struct {
	localPort  int
	remoteHost string
	remotePort int
	config     *tls.Config
}

// NewTLSClient creates a new TLS client proxy
func NewTLSClient(localPort int, remoteHost string, remotePort int, caCertPEM, clientCertPEM, clientKeyPEM []byte) (*TLSClient, error) {
	// Create certificate pool and add CA certificate
	caCertPool := x509.NewCertPool()
	if !caCertPool.AppendCertsFromPEM(caCertPEM) {
		return nil, fmt.Errorf("failed to append CA certificate")
	}

	// Load client certificate
	cert, err := tls.X509KeyPair(clientCertPEM, clientKeyPEM)
	if err != nil {
		return nil, fmt.Errorf("failed to load client certificate: %v", err)
	}

	// Create TLS config
	config := &tls.Config{
		RootCAs:      caCertPool,
		Certificates: []tls.Certificate{cert},
		MinVersion:   tls.VersionTLS12,
	}

	return &TLSClient{
		localPort:  localPort,
		remoteHost: remoteHost,
		remotePort: remotePort,
		config:     config,
	}, nil
}

// Start starts the non-TLS server and proxies connections to the TLS server
func (c *TLSClient) Start(ctx context.Context) error {
	listener, err := net.Listen("tcp", fmt.Sprintf("localhost:%d", c.localPort))
	if err != nil {
		return fmt.Errorf("failed to create listener: %v", err)
	}
	defer func() {
		_ = listener.Close()
	}()

	context.AfterFunc(ctx, func() {
		_ = listener.Close()
	})

	slog.Info("TLS client proxy listening", "local_port", c.localPort, "remote_host", c.remoteHost, "remote_port", c.remotePort)

	for {
		conn, err := listener.Accept()
		if err != nil {
			select {
			case <-ctx.Done():
				return nil
			default:
			}
			slog.Error("failed to accept connection", "error", err)
			continue
		}

		go c.handleConnection(ctx, conn)
	}
}

func (c *TLSClient) handleConnection(ctx context.Context, clientConn net.Conn) {
	defer clientConn.Close()

	// Connect to the remote TLS server
	remoteAddr := fmt.Sprintf("%s:%d", c.remoteHost, c.remotePort)
	tlsConn, err := tls.Dial("tcp", remoteAddr, c.config)
	if err != nil {
		slog.Error("failed to connect to remote TLS server", "remote_addr", remoteAddr, "error", err)
		return
	}
	defer func() {
		_ = tlsConn.Close()
	}()

	// Create channels to wait for either connection to close
	clientClosed := make(chan struct{})
	remoteClosed := make(chan struct{})

	// Copy data from client to remote
	go func() {
		_, err := io.Copy(tlsConn, clientConn)
		if err != nil && !errors.Is(err, io.EOF) {
			slog.Error("error copying from client to remote", "error", err)
		}
		close(clientClosed)
	}()

	// Copy data from remote to client
	go func() {
		_, err := io.Copy(clientConn, tlsConn)
		if err != nil && !errors.Is(err, io.EOF) {
			slog.Error("error copying from remote to client", "error", err)
		}
		close(remoteClosed)
	}()

	// Wait for either connection to close
	select {
	case <-clientClosed:
		_ = tlsConn.Close()
	case <-remoteClosed:
		_ = clientConn.Close()
	}
}

// GetGatewayIP returns the default gateway IP address by executing 'ip route'
func GetGatewayIP() (string, error) {
	// Execute 'ip route' command to get the default gateway
	cmd := exec.Command("ip", "route", "show", "default")
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("failed to execute ip route: %v", err)
	}

	// Parse the output to find the gateway
	// Example output: "default via 192.168.1.1 dev eth0"
	fields := strings.Fields(string(output))
	if len(fields) < 3 || fields[0] != "default" || fields[1] != "via" {
		return "", fmt.Errorf("unexpected ip route output format")
	}

	return fields[2], nil
}
