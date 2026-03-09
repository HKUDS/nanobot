package mcp

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
)

func (h *HTTPServer) protectedMetadata(w http.ResponseWriter, r *http.Request) {
	if h.protectedResourceMetadata == nil {
		// Not protected, return not found
		http.NotFound(w, r)
		return
	}

	protectedResourceMetadata := *h.protectedResourceMetadata

	scheme := r.Header.Get("X-Forwarded-Proto")
	if scheme == "" {
		scheme = "https"
	}
	host := r.Header.Get("X-Forwarded-Host")
	if host == "" {
		host = r.Host
	}
	protectedResourceMetadata.Resource = strings.TrimSuffix(fmt.Sprintf("%s://%s/%s", scheme, host, r.PathValue("path")), "/")

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(protectedResourceMetadata); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
	}
}
