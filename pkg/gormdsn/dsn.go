package gormdsn

import (
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/glebarez/sqlite"
	"gorm.io/driver/mysql"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func NewDBFromDSN(dsn string) (*gorm.DB, error) {
	var dialector gorm.Dialector

	switch {
	case strings.HasPrefix(dsn, "sqlite:") || strings.HasSuffix(dsn, ".db") || strings.Contains(dsn, ":memory:"):
		dsn = strings.TrimPrefix(dsn, "sqlite:")
		dialector = sqlite.Open(dsn)
	case strings.HasPrefix(dsn, "postgres://") || strings.HasPrefix(dsn, "postgresql://"):
		dialector = postgres.Open(dsn)
	case strings.HasPrefix(dsn, "mysql://") || strings.Contains(dsn, "@tcp("):
		dsn = strings.TrimPrefix(dsn, "mysql://")
		dialector = mysql.Open(dsn)
	default:
		return nil, fmt.Errorf("unsupported database type in DSN: %s", dsn)
	}

	return gorm.Open(dialector, &gorm.Config{
		Logger: logger.New(log.New(os.Stdout, "\r\n", log.LstdFlags), logger.Config{
			SlowThreshold:             200 * time.Millisecond,
			LogLevel:                  logger.Warn,
			IgnoreRecordNotFoundError: true,
			Colorful:                  true,
		}),
	})
}
