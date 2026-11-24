import { commandLocale } from "../../../packages/client-events/command-result"

/** POSIX message locale precedence; Windows may expose only the system locale. */
export function terminalLocale(): string {
  const raw = process.env.LC_ALL || process.env.LC_MESSAGES || process.env.LANG || Intl.DateTimeFormat().resolvedOptions().locale
  return commandLocale(raw)
}

const emptyFinalMessages: Record<string, string> = {
  en: "The model did not return a final reply.",
  es: "El modelo no devolvió una respuesta final.",
  fr: "Le modèle n’a pas fourni de réponse finale.",
  id: "Model tidak memberikan jawaban akhir.",
  ja: "モデルから最終回答が返されませんでした。",
  ko: "모델이 최종 답변을 반환하지 않았습니다.",
  "pt-BR": "O modelo não retornou uma resposta final.",
  vi: "Mô hình không trả về câu trả lời cuối cùng.",
  "zh-CN": "模型未返回最终答复。",
  "zh-TW": "模型未傳回最終答覆。",
}

export function emptyFinalResponseLine(): string {
  return emptyFinalMessages[terminalLocale()] ?? emptyFinalMessages.en!
}
