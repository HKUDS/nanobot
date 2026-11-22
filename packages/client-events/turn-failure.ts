// A delivered failure can belong to another task; don't imply that the active turn ended.
const messages = {
  en: { tool: "A tool failed before the request could finish", internal: "An internal error prevented the request from finishing" },
  es: { tool: "Una herramienta falló antes de completar la solicitud", internal: "Un error interno impidió completar la solicitud" },
  fr: { tool: "Un outil a échoué avant la fin de la requête", internal: "Une erreur interne a empêché la requête d’aboutir" },
  id: { tool: "Alat gagal sebelum permintaan selesai", internal: "Permintaan tidak dapat diselesaikan karena kesalahan internal" },
  ja: { tool: "リクエストが完了する前にツールでエラーが発生しました", internal: "内部エラーのためリクエストを完了できませんでした" },
  ko: { tool: "요청이 완료되기 전에 도구가 실패했습니다", internal: "내부 오류로 요청을 완료하지 못했습니다" },
  "pt-BR": { tool: "Uma ferramenta falhou antes de concluir a solicitação", internal: "Um erro interno impediu a conclusão da solicitação" },
  vi: { tool: "Một công cụ gặp lỗi trước khi yêu cầu hoàn tất", internal: "Không thể hoàn tất yêu cầu do lỗi nội bộ" },
  "zh-CN": { tool: "工具执行失败", internal: "请求因内部错误未能完成" },
  "zh-TW": { tool: "工具執行失敗", internal: "請求因內部錯誤未能完成" },
} satisfies Record<string, { tool: string; internal: string }>

export function nonModelFailureLine(kind: string | undefined, locale: string): string {
  const copy = Object.hasOwn(messages, locale) ? messages[locale as keyof typeof messages] : messages.en
  return kind === "tool" ? copy.tool : copy.internal
}
