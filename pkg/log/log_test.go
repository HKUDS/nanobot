package log

import (
	"bytes"
	"testing"
)

func TestRegexp(t *testing.T) {
	data := []byte(`{"data": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABJklEQVR42mJ8//8/AzSACZgAABgA","data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABJklEQVR42mJ8//8/AzSACZgAABgA"}`)
	expected := []byte(`{"data": "data:image/png;base64,iVBORw0KGgoAAAANSUhE...","data:image/png;base64,iVBORw0KGgoAAAANSUhE..."}`)
	data = Base64Replace.ReplaceAll(data, Base64Replacement)
	if bytes.Equal(data, expected) {
		t.Errorf("Expected data to be modified, but it was not. %s", data)
		t.Errorf("Expected data to be modified, but it was not. %s", expected)
	}
}

func TestRegexp2(t *testing.T) {
	data := []byte(`{"data": "VBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABJklEQVR42mJ8//8/AzSACZgAABgA","data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABJklEQVR42mJ8//8/AzSACZgAABgA"}`)
	expected := []byte(`{"data": "VBORw0KGgoAAAANSUhEU...","data:image/png;base64,iVBORw0KGgoAAAANSUhE..."}`)
	data = Base64Replace.ReplaceAll(data, Base64Replacement)
	if bytes.Equal(data, expected) {
		t.Errorf("Expected data to be modified, but it was not. %s", data)
		t.Errorf("Expected data to be modified, but it was not. %s", expected)
	}
}
