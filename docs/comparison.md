# Persocial vs the social suites and building blocks

Honest table, checked 2026-10-26. Persocial wins exactly one column group:
Arabic-dialect handling, local runs and an auditable judge — the things a
solo creator or small team needs to triage *their own* Instagram comments.
The big suites win everywhere else, plainly: native in-app hide/reply, many
platforms in one inbox, scheduling/publishing, analytics depth and human
support. If you need those, buy a suite.

| Tool | Arabic dialect / Arabizi | Runs locally | BYO LLM | Cost | Auditable judge | Native hide / reply | Multi-platform | Scheduling / publishing | Analytics | Support |
|---|---|---|---|---|---|---|---|---|---|---|
| **Persocial** | Yes — Gulf/MSA/Egyptian cues + Arabizi spellings, region packs[^1] | Yes — scoring + store on your machine[^1] | Yes — any OpenAI-compatible endpoint[^1] | Free (MIT)[^1] | Yes — every judge call stored with model, prompt, reason[^1] | No — decisions executed by hand, recorded as `ig_action`[^1] | No — Instagram comments only[^1] | No[^1] | Queue counters only[^1] | Community (issues)[^1] |
| Meta Business Suite (Hidden Words / moderation) | No model — keyword lists + opaque filters, no dialect/Arabizi handling[^2] | No — hosted[^3] | No[^3] | Free (no paid tier)[^3] | No — filters unexplained[^2] | **Yes — hide/delete/restrict in-app**[^2] | **Yes — FB + IG (+ Messenger/WhatsApp inbox)**[^3] | **Yes**[^3] | **Yes — Insights**[^3] | **Yes — help center, Meta Verified**[^4] |
| Sprout Social (Smart Inbox) | Limited — keyword monitoring, no dialect model[^5] | No — SaaS[^5] | No — built-in AI Assist[^5] | $199+/seat/mo (Standard, annual; Essentials $79–99)[^5] | No[^5] | **Yes**[^5] | **Yes**[^5] | **Yes**[^5] | **Yes — reports, listening add-on**[^5] | **Yes**[^5] |
| Hootsuite (Inbox) | Limited — no dialect model[^6] | No — SaaS[^6] | No — built-in AI assistant[^6] | $99+/user/mo (Standard; $199/$399 up)[^6] | No[^6] | **Yes**[^6] | **Yes**[^6] | **Yes — incl. bulk scheduling**[^6] | **Yes — incl. custom reports**[^6] | **Yes**[^6] |
| Brandwatch (listening + Engage) | Sentiment in 44 languages, no dialect/Arabizi packs[^7] | No — enterprise SaaS[^7] | No[^7] | Custom (≈$800+/mo entry)[^7] | No[^7] | Partial — workflow via Engage add-on[^7] | **Yes — 100M+ sources**[^7] | **Yes**[^7] | **Yes — consumer intelligence depth**[^7] | **Yes — enterprise**[^7] |
| Agorapulse (Inbox) | Limited — moderation rules, no dialect model[^8] | No — SaaS[^8] | No (AI replies custom plan only)[^8] | $79+/user/mo (Standard; Pro $119–149)[^8] | No[^8] | **Yes — incl. ad comments on Pro**[^8] | **Yes — 10 profiles/plan**[^8] | **Yes — unlimited**[^8] | **Yes**[^8] | **Yes**[^8] |
| Detoxify (open source) | No — 7 languages (EN/FR/ES/IT/PT/TR/RU), no Arabic[^9] | **Yes — PyTorch + Transformers**[^9] | No — fixed Jigsaw-trained models[^9] | Free (Apache-2.0)[^9] | No — scores only[^9] | No — library, no queue[^9] | No[^9] | No[^9] | No[^9] | Community[^9] |
| Perspective API (Jigsaw) | Partial — TOXICITY in Arabic + 17 languages, single axis, no dialect tuning[^10] | No — hosted API[^10] | No[^10] | Free (quota-limited)[^10] | No — scores without reasons[^10] | No — API, no queue[^10] | No[^10] | No[^10] | No[^10] | Docs / community[^10] |

## Where the suites win (use them when)

- You moderate **from inside the app** (one-tap hide, reply, report) or run
  ads whose comments need moderation — native actions beat an export loop.
- You run **five networks at once**, publish on a calendar, or report
  reach/engagement to a client — scheduling + analytics is their home turf.
- You need **a human on call** (SLAs, onboarding, regulated industries).

Persocial is the opposite bet: your own comments, your own machine, your
own LLM, and a receipt for every automated call.

---

[^1]: This repo: `docs/architecture.md`, `docs/taxonomy.md`, `docs/roadmap.md`. Accessed 2026-10-26.
[^2]: Instagram/Meta Hidden Words + comment controls: keyword filtering and in-app hide/delete/restrict — [AnyGen 2026 guide](https://www.anygen.io/showcase/how-to-unhide-a-comment-on-instagram/index.html), [SocialDay on Hidden Words](https://socialday.live/features/instagrams-photo-comments-ship-with-a-moderation-blind-spot-brands-cannot). Accessed 2026-10-26.
[^3]: Free, no paid tier; unified inbox; scheduling + Insights: [Buffer vs Meta Business Suite](https://buffer.com/resources/buffer-vs-meta-business-suite/), [Later on free schedulers](https://later.Com/blog/social-media-scheduling-tools/), [RecurPost alternatives roundup](https://recurpost.com/compare/alternatives/meta-business-suite/). Accessed 2026-10-26.
[^4]: Meta Verified / help-center support: [RecurPost vs Meta Business Suite](https://recurpost.com/compare/recurpost-vs-meta-business-suite/). Accessed 2026-10-26.
[^5]: Smart Inbox from Standard $199/seat/mo annual ($249 monthly); Essentials $79–99; AI Assist on higher tiers: [Buffer vs Sprout](https://buffer.com/resources/buffer-vs-sprout-social/), [VistaSocial comparison](https://vistasocial.com/insights/sprout-social-vs-buffer-vs-vista-social/), [G2 pricing](https://www.g2.com/products/sprout-social/pricing). Accessed 2026-10-26.
[^6]: Standard $99/user/mo, Professional $199, Advanced $399 (annual); unified inbox, AI assistant, bulk scheduling, custom reports: [NapoleonCat Oct-2026 pricing](https://napoleoncat.com/blog/hootsuite-pricing/), [CostBench](https://costbench.com/software/social-media-management/hootsuite/), [socialrails pricing](https://socialrails.com/blog/hootsuite-pricing). Accessed 2026-10-26.
[^7]: Enterprise listening ≈$800+/mo entry, custom quotes; sentiment in 44 languages; 100M+ sources: [ListeningPlatforms comparison](https://listeningplatforms.com/compare/brandwatch-vs-talkwalker/?utm_source=openai), [Zigpoll pricing table](https://www.zigpoll.com/content/what-are-the-most-effective-social-listening-platforms-for-tracking-emerging-trends-and-sentiment-analysis-in-realtime-across-multiple-languages), [Allable](https://www.allable.ai/blog/social-media-monitoring-tools/). Accessed 2026-10-26.
[^8]: Standard $79/user/mo annual ($99 monthly), Professional $119–149; unified inbox, moderation rules, saved replies, ad-comment moderation on Pro: [VistaSocial](https://vistasocial.com/insights/hootsuite-vs-agorapulse-vs-vista-social/), [Buffer vs Agorapulse](https://buffer.com/resources/buffer-vs-agorapulse/), [socialrails moderation guide](https://socialrails.com/blog/social-media-moderation-tools-guide). Accessed 2026-10-26.
[^9]: Open-source (Apache-2.0) toxic-comment classifier on PyTorch/Transformers; `multilingual` covers EN/FR/ES/IT/PT/TR/RU: [unitaryai/detoxify](https://github.com/unitaryai/detoxify), [EveryDev listing](https://www.everydev.ai/tools/detoxify). Accessed 2026-10-26.
[^10]: Free hosted toxicity API by Jigsaw; TOXICITY production attribute in Arabic + 17 languages since the 2021 expansion; scores only, no local run: [Perspective attributes + languages](https://support.perspectiveapi.com/s/about-the-api-attributes-and-languages), [Jigsaw 10-new-languages launch](https://www.findglocal.com/US/New-York/847768338655107/Jigsaw). Accessed 2026-10-26.
