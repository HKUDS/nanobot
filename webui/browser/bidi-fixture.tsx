import { MessageBubble } from "@/components/MessageBubble";
import { ThreadComposer } from "@/components/thread/ThreadComposer";

const answer = "# בדיקת החיבור ל־GitHub\n\nאפשר לקרוא את המדריך ולהריץ את `git status` מתוך סביבת העבודה.\n\nThis paragraph starts in English and includes עברית (Hebrew).\n\n- בדקו שהערך של `API_KEY` מוגדר.\n- ודאו שהכתובת Base URL נכונה.\n\n> אפשר לשמור את ההגדרות לפני שממשיכים.\n\n```bash\ngit status --short\ngit log --oneline -5\n```";

export function BidiFixture() {
  return <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
    <MessageBubble message={{ id: "question", role: "user", content: "איך בודקים את החיבור ל־GitHub?", createdAt: 1 }} />
    <MessageBubble message={{ id: "answer", role: "assistant", content: answer, createdAt: 2 }} />
    <ThreadComposer modelLabel="GPT" persistDraft={false} onSend={() => {}} />
  </main>;
}
