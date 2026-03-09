package api

import "net/http"

func routes(s *server, mux *http.ServeMux) {
	mux.Handle("GET /api/events/{thread_id}", s.withContext(Events))
	mux.Handle("GET /api/version", s.api(Version))
}
