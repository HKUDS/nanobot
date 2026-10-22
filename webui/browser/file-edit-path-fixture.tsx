import { useState } from "react";
import { FileEditGroup, type FileEditSummary } from "@/components/thread/activity/FileEditRow";

export const longEditPath = "C:/Users/HR/.nanobot-ncode/workspace/artifacts/nan284-local-file-attachments/review-fixes-20261022-133833/serve_fixture.py";
const paths = [longEditPath, "src/verify.py", `C:/项目/带空格的目录/${"very_long_file_name_".repeat(12)}verify.py`];
export function FileEditPathFixture() {
  const [opened, setOpened] = useState("");
  return <main className="p-4">
    <section aria-label="File edits" style={{ maxWidth: 640 }}>
      {paths.map((path, index) => {
        const edit: FileEditSummary = {
          key: path, path, added: index === 1 ? 33 : 12345, deleted: index === 1 ? 0 : 6789,
          approximate: false, binary: false, status: "done", pending: false,
          diff: { format: "unified", text: "--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new\n" },
        };
        return <FileEditGroup key={path} edits={[edit]} displayMode="collapsed_diff" onOpenFilePreview={setOpened} />;
      })}
    </section>
    <output aria-label="Opened file">{opened}</output>
  </main>;
}
