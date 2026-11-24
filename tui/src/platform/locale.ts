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

const outputLimitMessages: Record<string, string> = {
  en: "The model reached its output limit before returning a final answer.",
  es: "El modelo alcanzó su límite de salida antes de dar una respuesta final.",
  fr: "Le modèle a atteint sa limite de sortie avant de donner une réponse finale.",
  id: "Model mencapai batas keluaran sebelum memberikan jawaban akhir.",
  ja: "モデルは最終回答を返す前に出力上限に達しました。",
  ko: "모델이 최종 답변을 반환하기 전에 출력 한도에 도달했습니다.",
  "pt-BR": "O modelo atingiu o limite de saída antes de dar uma resposta final.",
  vi: "Mô hình đã đạt giới hạn đầu ra trước khi đưa ra câu trả lời cuối cùng.",
  "zh-CN": "模型在给出最终答复前已达到输出上限。",
  "zh-TW": "模型在給出最終答覆前已達輸出上限。",
}

function localizedLine(messages: Record<string, string>): string {
  return messages[terminalLocale()] ?? messages.en!
}

export function emptyFinalResponseLine(errorKind?: string): string | undefined {
  if (errorKind === "empty_final_response_length") return localizedLine(outputLimitMessages)
  if (errorKind === "empty_final_response") return localizedLine(emptyFinalMessages)
  return undefined
}
