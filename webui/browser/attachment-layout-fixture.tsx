import { MessageBubble } from "@/components/MessageBubble";
import type { UIMediaAttachment, UIMessage } from "@/lib/types";
import sampleVideo from "@/dev/gallery/fixtures/sample.webm";

function image(name: string, color: string): UIMediaAttachment {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="${color}"/><circle cx="160" cy="100" r="55" fill="white" fill-opacity=".55"/></svg>`;
  return { kind: "image", name, url: `data:image/svg+xml,${encodeURIComponent(svg)}` };
}

// A valid 22-byte empty ZIP keeps the native browser download deterministic.
const archive: UIMediaAttachment = { kind: "file", name: "archive.zip", url: "data:application/zip;base64,UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==" };
const files: UIMediaAttachment[] = [
  { ...archive, name: "release-deliverables-with-a-very-long-English-filename-for-layout-regression.zip" },
  { kind: "file", name: "项目交付资料与详细验收记录包含中英文的超长文件名称-final-review.pdf", url: "/fixture/report.pdf" },
  { kind: "file", url: "/fixture/unnamed" },
];
const samples: { label: string; message: UIMessage }[] = [
  {
    label: "Assistant mixed attachments",
    message: {
      id: "assistant-mixed", role: "assistant", content: "Three image studies and the source archive.", createdAt: 1,
      media: [image("Coral study.svg", "#e88b7b"), archive, image("Blue study.svg", "#83a9d8"), image("Green study.svg", "#83ba9c")],
    },
  },
  {
    label: "User mixed attachments",
    message: {
      id: "user-mixed", role: "user", content: "Please review this image and archive.", createdAt: 2,
      media: [archive, image("User study.svg", "#c9a2d7")],
    },
  },
  {
    label: "Multiple files and long names",
    message: {
      id: "multiple-files", role: "assistant", content: "Download the full deliverables.", createdAt: 3,
      media: files,
    },
  },
  {
    label: "User multiple files",
    message: { id: "user-files", role: "user", content: "Review these files together.", createdAt: 4, media: files },
  },
  {
    label: "Playable video",
    message: { id: "video", role: "assistant", content: "A small playable clip.", createdAt: 4, media: [{ kind: "video", name: "sample.webm", url: sampleVideo }] },
  },
  {
    label: "Retry video",
    message: { id: "retry-video", role: "assistant", content: "Retry when the clip becomes available.", createdAt: 5, media: [{ kind: "video", name: "retry.webm", url: "/fixture/retry.webm" }] },
  },
  {
    label: "Pending attachment",
    message: { id: "pending", role: "user", content: "Uploading the archive.", createdAt: 6, deliveryStatus: "sending", media: [{ kind: "file", name: "pending.zip" }] },
  },
  {
    label: "Unavailable attachment",
    message: { id: "unavailable", role: "assistant", content: "This file is no longer available.", createdAt: 7, media: [{ kind: "file", name: "unavailable.pdf" }] },
  },
];

export function AttachmentLayoutFixture() {
  return <main className="space-y-8 px-4 py-6">
    {samples.map(({ label, message }) => <section key={message.id} aria-label={label}>
      <h2 className="mb-3 text-xs font-medium text-muted-foreground">{label}</h2>
      <MessageBubble message={message} />
    </section>)}
  </main>;
}
