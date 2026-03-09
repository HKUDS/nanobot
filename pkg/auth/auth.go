package auth

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"

	"github.com/nanobot-ai/nanobot/pkg/mcp"
	"github.com/nanobot-ai/nanobot/pkg/types"
	"github.com/obot-platform/mcp-oauth-proxy/pkg/oauth/validate"
	"github.com/obot-platform/mcp-oauth-proxy/pkg/proxy"
	proxytypes "github.com/obot-platform/mcp-oauth-proxy/pkg/types"
)

type Auth struct {
	OAuthClientID        string   `usage:"OAuth client ID"`
	OAuthClientSecret    string   `usage:"OAuth client secret"`
	OAuthAuthorizeURL    string   `usage:"OAuth authorize URL for third-party OAuth provider"`
	OAuthTokenURL        string   `usage:"OAuth token URL for third-party OAuth provider"`
	OAuthJWKSURL         string   `usage:"OAuth JWKS URL to trust in addition to tokens"`
	OAuthScopes          []string `usage:"OAuth scopes to request during OAuth flow"`
	TrustedIssuer        string   `usage:"Trusted issuer for JWT tokens"`
	JWKS                 string   `usage:"JWKS public key for JWT tokens"`
	TrustedAudiences     []string `usage:"Trusted audiences for JWT tokens"`
	EncryptionKey        string   `usage:"Encryption key for storing sensitive data"`
	APIKeyAuthWebhookURL string   `usage:"URL for API key authentication webhook"`
	MCPServerID          string   `usage:"ID of the MCP server to validate API keys for"`
}

func Wrap(ctx context.Context, env map[string]string, auth Auth, dsn, healthzPath string, next http.Handler) (http.Handler, error) {
	if auth.OAuthClientID == "" {
		slog.Info("auth middleware disabled, oauth client ID not configured")
		return next, nil
	}
	slog.Info("auth middleware enabled", "healthz_path", healthzPath)

	next, err := setupContext(auth, next)
	if err != nil {
		return nil, err
	}

	if auth.OAuthClientID != "" {
		if auth.OAuthClientSecret == "" {
			return nil, fmt.Errorf("oauthClientSecret is required")
		}
		if auth.OAuthAuthorizeURL == "" {
			return nil, fmt.Errorf("oauthAuthorizeURL is required")
		}

		proxy, err := mcpProxy(auth, dsn, next)
		if err != nil {
			return nil, fmt.Errorf("failed to create oauth proxy: %w", err)
		}
		slog.Info("oauth proxy created")

		if healthzPath != "" {
			return http.HandlerFunc(func(rw http.ResponseWriter, req *http.Request) {
				if req.URL.Path == healthzPath {
					next.ServeHTTP(rw, req)
					return
				}

				proxy.ServeHTTP(rw, req)
			}), nil
		}

		return proxy, nil
	}

	return next, nil
}

func userFromHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(rw http.ResponseWriter, req *http.Request) {
		var user mcp.User
		keys := map[string]any{}
		_ = mcp.JSONCoerce(user, &keys)
		for key := range keys {
			v := req.Header.Get("X-Forwarded-" + strings.ReplaceAll(key, "_", "_"))
			if key == "email_verified" {
				keys[key] = v == "true"
			} else {
				keys[key] = v
			}
		}
		_ = mcp.JSONCoerce(keys, &user)

		if user.ID == "" {
			user.ID = user.Sub
		}
		if user.ID == "" {
			user.ID = user.Login
		}

		nctx := types.NanobotContext(req.Context())
		nctx.User = user
		ctx := types.WithNanobotContext(mcp.WithUser(req.Context(), user), nctx)
		if token, _ := keys["access_token"].(string); token != "" {
			ctx = mcp.WithToken(ctx, token)
		}
		next.ServeHTTP(rw, req.WithContext(ctx))
	})
}

func setupContext(auth Auth, next http.Handler) (http.Handler, error) {
	if auth.OAuthClientID == "" {
		return userFromHeaders(next), nil
	}
	return http.HandlerFunc(func(rw http.ResponseWriter, req *http.Request) {
		info := validate.GetTokenInfo(req)
		if info != nil {
			var user mcp.User
			infoString, ok := info.Props["info"].(string)
			if ok {
				_ = json.Unmarshal([]byte(infoString), &user)
			}
			nctx := types.NanobotContext(req.Context())
			if user.ID == "" {
				user.ID = user.Sub
			}
			if user.ID == "" {
				user.ID = user.Login
			}

			nctx.User = user
			ctx := types.WithNanobotContext(mcp.WithUser(req.Context(), user), nctx)
			if token, _ := info.Props["access_token"].(string); token != "" {
				ctx = mcp.WithToken(ctx, token)
			}
			slog.Debug("oauth token info applied to request context", "user_id", user.ID, "request_path", req.URL.Path)
			req = req.WithContext(ctx)
		}
		next.ServeHTTP(rw, req)
	}), nil
}

func mcpProxy(auth Auth, dsn string, next http.Handler) (http.Handler, error) {
	hash := sha256.Sum256([]byte(strings.TrimSpace(auth.EncryptionKey)))

	if !strings.Contains(dsn, "postgres") {
		dsn = strings.TrimSuffix(dsn, ".db") + "_auth.db"
	}
	slog.Info("initializing oauth proxy")

	proxy, err := proxy.NewOAuthProxy(&proxytypes.Config{
		DatabaseDSN:          dsn,
		OAuthClientID:        auth.OAuthClientID,
		OAuthClientSecret:    auth.OAuthClientSecret,
		OAuthAuthorizeURL:    auth.OAuthAuthorizeURL,
		ScopesSupported:      strings.Join(auth.OAuthScopes, ","),
		EncryptionKey:        base64.StdEncoding.EncodeToString(hash[:]),
		Mode:                 "middleware",
		MCPPaths:             []string{"/mcp", "/api"},
		OAuthJWKSURL:         auth.OAuthJWKSURL,
		CookieNamePrefix:     "nanobot_",
		APIKeyAuthWebhookURL: auth.APIKeyAuthWebhookURL,
		MCPServerID:          auth.MCPServerID,
	})
	if err != nil {
		return nil, err
	}

	mux := http.NewServeMux()
	proxy.SetupRoutes(mux, next)
	return mux, nil
}
