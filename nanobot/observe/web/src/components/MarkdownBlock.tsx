import React from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

export default function MarkdownBlock(props: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{props.text}</ReactMarkdown>
    </div>
  )
}
