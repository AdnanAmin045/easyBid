"use client";

import { useRouter } from "next/navigation";
import { CampaignForm, EMPTY_CAMPAIGN } from "@/components/campaign-form";
import { PageHeader } from "@/components/ui";
import { api, type Campaign, type CampaignInput } from "@/lib/api";

export default function NewCampaignPage() {
  const router = useRouter();

  async function create(input: CampaignInput) {
    const campaign = await api<Campaign>("/outreach/campaigns", { method: "POST", body: input });
    // The list of people comes next, on the campaign's own page.
    router.push(`/outreach/campaigns/${campaign.id}`);
  }

  return (
    <>
      <PageHeader
        title="New campaign"
        subtitle="Write the email once, then paste or upload your list. Worklane sends them slowly, from your own Gmail, and stops if anything looks wrong."
      />
      <CampaignForm initial={EMPTY_CAMPAIGN} submitLabel="Create campaign and add recipients" onSubmit={create} />
    </>
  );
}
