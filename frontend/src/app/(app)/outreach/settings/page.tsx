import { redirect } from "next/navigation";

// Email settings live in one place now.
export default function Page() {
  redirect("/email-settings");
}
