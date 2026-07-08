import { ChatTestPage } from "@/components/chatbot/chat-test-page";

export default function ChatConsoleRoute({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return <ChatTestPage paramsPromise={params} />;
}
