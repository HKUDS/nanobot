interface PaletteCopy {
  empty: string
  page: (range: string, total: number) => string
  choose: string
  complete: string
  close: string
}

const english: PaletteCopy = {
  empty: "No matches", page: (r, n) => `${r} of ${n}`, choose: "choose", complete: "complete", close: "close",
}

const copy: Record<string, PaletteCopy> = {
  en: english,
  "zh-CN": { empty: "无匹配命令", page: (r, n) => `${r}，共 ${n} 项`, choose: "选择", complete: "补全", close: "关闭" },
  "zh-TW": { empty: "沒有相符的指令", page: (r, n) => `${r}，共 ${n} 項`, choose: "選擇", complete: "補齊", close: "關閉" },
  fr: { empty: "Aucun résultat", page: (r, n) => `${r} sur ${n}`, choose: "choisir", complete: "compléter", close: "fermer" },
  ja: { empty: "一致するコマンドはありません", page: (r, n) => `全 ${n} 件中 ${r} 件`, choose: "選択", complete: "補完", close: "閉じる" },
  ko: { empty: "일치하는 명령 없음", page: (r, n) => `전체 ${n}개 중 ${r}`, choose: "선택", complete: "자동 완성", close: "닫기" },
  es: { empty: "Sin coincidencias", page: (r, n) => `${r} de ${n}`, choose: "elegir", complete: "completar", close: "cerrar" },
  "pt-BR": { empty: "Nenhum comando encontrado", page: (r, n) => `${r} de ${n}`, choose: "escolher", complete: "completar", close: "fechar" },
  vi: { empty: "Không có lệnh phù hợp", page: (r, n) => `${r} trong ${n}`, choose: "chọn", complete: "điền lệnh", close: "đóng" },
  id: { empty: "Tidak ada perintah yang cocok", page: (r, n) => `${r} dari ${n}`, choose: "pilih", complete: "lengkapi", close: "tutup" },
}

export function commandPaletteCopy(locale: string): PaletteCopy {
  return copy[locale] ?? english
}
