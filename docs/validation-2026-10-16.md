# Tbilisi real-site validation · 16 October 2026

Base: `f8fb3862c23e7b0a680c8a6f1ed6a8069521b19d`, release candidate rc3.

The deployed app opened cleanly in a fresh browser as a guest. Live Golden Spot for **Tbilisi, Georgia** discovered **15 candidates**. Surrounding-map enrichment required 50 tiles and stopped after a failed request/timeout; it correctly showed an unranked inventory, not an automatic top five.

The same app was exercised with Streamlit AppTest, real external provider calls and isolated local storage. Each site had a separately named project; no user database writes or existing project modifications were performed. The first three real sites completed before adding the country logistics section.

| Site | Live analysis duration | Routing | Model population / 15 min | 30 min | 40 min | App exceptions |
|---|---:|---|---:|---:|---:|---:|
| East Point | 86.3 s | Valhalla | 232,454 | 697,587 | 1,131,735 | 0 |
| Tbilisi Mall | 77.4 s | Valhalla | 178,892 | 759,303 | 1,043,209 | 0 |
| City Mall Saburtalo | 121.3 s | Valhalla | 148,847 | 683,865 | 1,088,398 | 0 |
| City Mall Gldani | 145.4 s | Valhalla | 275,704 | 635,871 | 987,627 | 0 |
| Galleria Tbilisi | 159.3 s | Valhalla | 251,938 | 951,968 | 1,284,944 | 0 |

Population figures are WorldPop 2025 model estimates within returned road-network polygons. They are not measured footfall, current census counts, unique network customers or an investment ranking. Catchments overlap and must not be summed across malls. Full polygons/provider evidence are retained in the separate Tbilisi export/report, not committed as user projects.

## Findings and fixes

- The WorldPop response for requested ages 0-18 includes a complete 15-19 class. The previous summation overclaimed that age range. The fix rejects a boundary-crossing band; exact children 0-18 is unavailable until suitable single-year evidence or an explicitly approved estimation method exists. Existing raw age-band responses are not presented as exact children counts.
- Project saves previously retained commercial/metadata values without the live evidence. Matching analysis now has a dated snapshot in the same project and a separate export. Mismatching-location evidence cannot attach to a project.
- Golden Spot now exports its metadata and results, including incomplete/unranked discovery.
- Source-checked Georgia logistics and an independent Tbilisi analyst survey priority were added after the real-site core gate. Neither bypasses Golden Spot's missing-context rule.

Create/save and JSON export/import round trips passed for five isolated candidate projects. Local tests: **83 passed**; dependency lock check, compilation and diff whitespace checks passed. The actual Supabase database responded to metadata/project-library/policy reads. Personal and company project-library tables returned no rows; a signed-in application save was not tested. No RLS, grants, credentials or database schema were changed.

## Publication limitation

The only accessible deployed session was a guest. A Tirana project/backup was not present in that session or in returned cloud library rows. README explicitly warns that deployment restarts lose guest projects. Changes are therefore prepared in a separate branch/PR without updating the deployment's main branch. Publish only after confirming a durable Tirana backup or authenticated transfer. This is not a claim that Tirana is deleted or absent from the user's other sessions.
