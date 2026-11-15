import { useEffect, useState } from "react";

export function useObjectUrl(blob: Blob | null): string | null {
  const [value, setValue] = useState<{ blob: Blob; url: string } | null>(null);
  useEffect(() => {
    if (!blob) { setValue(null); return; }
    const url = URL.createObjectURL(blob);
    setValue({ blob, url });
    return () => URL.revokeObjectURL(url);
  }, [blob]);
  return value?.blob === blob ? value.url : null;
}
