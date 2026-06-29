import { ServiceRequestChat } from "@/components/chatbot/ServiceRequestChat";
import { AuthGuard } from "@/components/auth/AuthGuard";

export const metadata = {
  title: "Service Request – Cenomi",
  description: "Conversational service request assistant",
};

export default function ServiceRequestChatPage() {
  return (
    <AuthGuard>
      <ServiceRequestChat />
    </AuthGuard>
  );
}
