import { redirect } from "next/navigation";

export default function HomePage() {
  // Redirect to chat; the chat page checks auth client-side and redirects to /login
  redirect("/service-request-chat");
}
