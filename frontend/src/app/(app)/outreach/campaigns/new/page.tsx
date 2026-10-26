"use client";

import { useRouter } from "next/navigation";
import { CampaignForm, EMPTY_CAMPAIGN } from "@/components/campaign-form";
import { Loading, PageHeader } from "@/components/ui";
import { api, useApi, type Campaign, type CampaignInput, type OutreachSettings } from "@/lib/api";

export default function NewCampaignPage() {
  const router = useRouter();
  const { data: settings } = useApi<OutreachSettings>("/outreach/settings");

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
      {settings ? (
        <CampaignForm
          // The schedule a campaign starts with comes from Email settings.
          initial={{
            ...EMPTY_CAMPAIGN,
            min_delay_seconds: settings.default_min_delay_seconds,
            max_delay_seconds: settings.default_max_delay_seconds,
            daily_limit: settings.default_campaign_daily_limit,
            window_start_hour: settings.default_window_start_hour,
            window_end_hour: settings.default_window_end_hour,
            timezone: settings.default_timezone,
            weekdays_only: settings.default_weekdays_only,
            ramp_up: settings.default_ramp_up,
          }}
          submitLabel="Create campaign and add recipients"
          onSubmit={create}
        />
      ) : (
        <Loading />
      )}
    </>
  );
}
