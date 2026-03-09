package auditlogs

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"log/slog"
)

type Collector struct {
	auditBuffer      []MCPAuditLog
	auditLock        sync.Mutex
	auditLogMetadata map[string]string
	kickAuditPersist chan struct{}
	done             chan struct{}
	sendURL, token   string
}

func NewCollector(sendURL, token string, batchSize int, flushInterval time.Duration, auditLogMetadata map[string]string) *Collector {
	c := &Collector{
		sendURL:          sendURL,
		token:            token,
		done:             make(chan struct{}),
		auditBuffer:      make([]MCPAuditLog, 0, 2*batchSize),
		kickAuditPersist: make(chan struct{}),
		auditLogMetadata: auditLogMetadata,
	}

	go c.runPersistenceLoop(flushInterval)

	return c
}

// Close closes the collector and waits for all pending audit logs to be persisted.
func (c *Collector) Close() {
	if c == nil {
		return
	}

	close(c.kickAuditPersist)
	<-c.done
}

func (c *Collector) CollectMCPAuditEntry(entry MCPAuditLog) {
	if c == nil || entry.CallType == "" {
		// If the call type is empty, then this is a response to a request.
		// The audit log will be handled elsewhere.
		return
	}

	if entry.ClientName == "nanobot-ui" && strings.HasPrefix(entry.CallIdentifier, "chat://") && entry.CallType == "resources/read" {
		// These are spammy audit logs that we do not need to send, as they never contain useful information.
		return
	}

	entry.Metadata = c.auditLogMetadata

	c.auditLock.Lock()
	defer c.auditLock.Unlock()

	c.auditBuffer = append(c.auditBuffer, entry)
	if len(c.auditBuffer) >= cap(c.auditBuffer)/2 {
		select {
		case c.kickAuditPersist <- struct{}{}:
		default:
		}
	}
}

func (c *Collector) runPersistenceLoop(flushInterval time.Duration) {
	timer := time.NewTimer(flushInterval)
	defer timer.Stop()
	defer close(c.done)

	var closed bool
	for {
		select {
		case _, closed = <-c.kickAuditPersist:
			timer.Stop()
		case <-timer.C:
		}

		if err := c.persistAuditLogs(); err != nil {
			slog.Error("failed to persist audit log", "error", err)
		}

		if closed {
			return
		}

		timer.Reset(flushInterval)
	}
}

func (c *Collector) persistAuditLogs() error {
	c.auditLock.Lock()
	if len(c.auditBuffer) == 0 {
		c.auditLock.Unlock()
		return nil
	}

	buf := c.auditBuffer
	c.auditBuffer = make([]MCPAuditLog, 0, cap(c.auditBuffer))
	c.auditLock.Unlock()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := c.sendMCPAuditLogs(ctx, buf); err != nil {
		c.auditLock.Lock()
		c.auditBuffer = append(buf, c.auditBuffer...)
		c.auditLock.Unlock()
		return err
	}

	return nil
}

func (c *Collector) sendMCPAuditLogs(ctx context.Context, logs []MCPAuditLog) error {
	h := http.Client{
		Timeout: 10 * time.Second,
	}

	jsonBytes, err := json.Marshal(logs)
	if err != nil {
		return err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.sendURL, bytes.NewBuffer(jsonBytes))
	if err != nil {
		return err
	}

	if c.token != "" {
		req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", c.token))
	}

	resp, err := h.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("unexpected status code sending audit logs %d: %s", resp.StatusCode, string(bodyBytes))
	}

	return nil
}
