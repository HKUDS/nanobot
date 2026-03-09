package session

import (
	"fmt"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// migrateSessionWorkflowURIs migrates the workflow_uris column of the sessions table into rows in the workflow_runs table.
// After a successful migration, the workflow_uris column is dropped from the sessions table.
func migrateSessionWorkflowURIs(tx *gorm.DB) error {
	if !tx.Migrator().HasColumn(&Session{}, "workflow_uris") {
		return nil
	}

	rows, err := tx.
		Table("sessions").
		Select("session_id", "workflow_uris").
		Where("workflow_uris IS NOT NULL").
		Rows()
	if err != nil {
		return err
	}
	defer rows.Close()

	var runs []WorkflowRun
	for rows.Next() {
		var (
			sessionID string
			raw       any
		)

		if err := rows.Scan(&sessionID, &raw); err != nil {
			return err
		}
		if sessionID == "" {
			continue
		}

		var uris []string
		if err := scan(raw, &uris); err != nil {
			return fmt.Errorf("failed to decode workflow_uris for session %s: %w", sessionID, err)
		}

		for _, uri := range uris {
			if uri == "" {
				continue
			}
			run := WorkflowRun{
				SessionID:   sessionID,
				WorkflowURI: uri,
			}
			runs = append(runs, run)
		}
	}

	if err := rows.Err(); err != nil {
		return err
	}

	if len(runs) > 0 {
		if err := tx.
			Clauses(clause.OnConflict{DoNothing: true}).
			CreateInBatches(runs, 500).Error; err != nil {
			return err
		}
	}

	return tx.Migrator().DropColumn(&Session{}, "workflow_uris")
}
