package session

import (
	"compress/gzip"
	"io"
	"io/fs"
	"mime"
	"net/http"
	"net/http/httputil"
	"net/url"
	"path/filepath"
	"strings"

	"github.com/nanobot-ai/nanobot/packages/ui"
)

func getCookieID(req *http.Request) string {
	cookie, err := req.Cookie("nanobot-session-id")
	if err == nil {
		return cookie.Value
	}
	return ""
}

func UISession(next http.Handler, sessionStore *Manager, apiHandler http.Handler) http.Handler {
	return http.HandlerFunc(func(rw http.ResponseWriter, req *http.Request) {
		if !strings.Contains(strings.ToLower(req.UserAgent()), "mozilla") {
			next.ServeHTTP(rw, req)
			return
		}

		//nctx := types.NanobotContext(req.Context())
		//user := nctx.User
		//nanobotSessionID := getCookieID(req)

		//if nanobotSessionID != "" {
		//	session, err := sessionStore.DB.GetByIDByAccountID(req.Context(), nanobotSessionID, complete.First(user.ID, nanobotSessionID))
		//	if errors.Is(err, gorm.ErrRecordNotFound) {
		//		nanobotSessionID = ""
		//	} else if err != nil {
		//		http.Error(rw, "Failed to load session: "+err.Error(), http.StatusInternalServerError)
		//		return
		//	}
		//	nanobotSessionID = session.SessionID
		//}

		//if nanobotSessionID == "" {
		//	nanobotSessionID = uuid.String()
		//	err := sessionStore.DB.Create(req.Context(), &Session{
		//		Type:      "ui",
		//		SessionID: nanobotSessionID,
		//		AccountID: complete.First(user.ID, nanobotSessionID),
		//		State: State{
		//			InitializeResult: mcp.InitializeResult{},
		//			InitializeRequest: mcp.InitializeRequest{
		//				Capabilities: mcp.ClientCapabilities{
		//					Elicitation: &struct{}{},
		//				},
		//			},
		//		},
		//	})
		//	if err != nil {
		//		http.Error(rw, "Failed to create session: "+err.Error(), http.StatusInternalServerError)
		//		return
		//	}

		//	cookie := http.Cookie{
		//		Name:     "nanobot-session-id",
		//		Value:    nanobotSessionID,
		//		Secure:   isSecureRequest(req),
		//		Path:     "/",
		//		HttpOnly: true,
		//	}
		//	if cookie.Secure {
		//		cookie.SameSite = http.SameSiteNoneMode
		//	}
		//	http.SetCookie(rw, &cookie)
		//}

		//if user.ID == "" {
		//	user.ID = nanobotSessionID
		//	nctx.User = user
		//	req = req.WithContext(types.WithNanobotContext(req.Context(), nctx))
		//}
		//
		//if req.Header.Get("Mcp-Session-Id") == "" {
		//	req.Header.Set("Mcp-Session-Id", nanobotSessionID)
		//}

		if strings.HasPrefix(req.URL.Path, "/mcp") {
			next.ServeHTTP(rw, req)
			return
		}

		if strings.HasPrefix(req.URL.Path, "/api") {
			apiHandler.ServeHTTP(rw, req)
			return
		}

		uiFS, _ := fs.Sub(ui.FS, "dist")
		_, err := fs.Stat(uiFS, "fallback.html")
		if err == nil {
			if _, err := fs.Stat(uiFS, strings.TrimPrefix(req.URL.Path, "/")); err == nil {
				if strings.Contains(req.URL.Path, "immutable") {
					serveGzipAndCached(req, rw, uiFS)
				} else {
					http.FileServer(http.FS(uiFS)).ServeHTTP(rw, req)
				}
			} else {
				http.ServeFileFS(rw, req, uiFS, "fallback.html")
			}
		} else {
			url, _ := url.ParseRequestURI("http://localhost:5173")
			httputil.NewSingleHostReverseProxy(url).ServeHTTP(rw, req)
		}
	})
}

func isSecureRequest(req *http.Request) bool {
	return req.TLS != nil || req.Header.Get("X-Forwarded-Proto") == "https"
}

func serveGzipAndCached(req *http.Request, rw http.ResponseWriter, fs fs.FS) {
	path := req.URL.Path
	file, err := fs.Open(strings.TrimPrefix(path, "/"))
	if err != nil {
		http.Error(rw, "File not found", http.StatusNotFound)
		return
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil {
		http.Error(rw, "File stat error", http.StatusInternalServerError)
		return
	}

	// Set cache headers
	rw.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
	rw.Header().Set("Last-Modified", info.ModTime().UTC().Format(http.TimeFormat))

	ctype := mime.TypeByExtension(filepath.Ext(path))
	if ctype == "" {
		ctype = http.DetectContentType(nil)
	}
	rw.Header().Set("Content-Type", ctype)

	// Check if client accepts gzip
	if strings.Contains(req.Header.Get("Accept-Encoding"), "gzip") {
		rw.Header().Set("Content-Encoding", "gzip")
		rw.Header().Del("Content-Length")
		gz := gzip.NewWriter(rw)
		defer gz.Close()
		io.Copy(gz, file)
		return
	}

	// Serve uncompressed
	io.Copy(rw, file)
}
