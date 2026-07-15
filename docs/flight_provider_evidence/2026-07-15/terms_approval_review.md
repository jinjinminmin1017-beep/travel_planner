# Terms, robots and enablement review

Review date: 2026-07-15 (Asia/Shanghai)

Decision for `airline_mu_public_query`, `airline_cz_public_query` and `airline_sc_public_query`: **PENDING_REVIEW / keep disabled**.

## Evidence reviewed

- China Eastern privacy policy: <https://global.ceair.com/global/static/ceairRules/LegalAndPrivacyTerms/>. It expressly describes anonymous browsing and basic flight search, Cookies and security/risk-control logging. It does not grant a third party permission to automate or reuse an undocumented query endpoint.
- China Eastern `https://www.ceair.com/robots.txt`: returned HTTP 403 to a non-browser request during this review. No affirmative crawler permission was obtained.
- China Southern `https://www.csair.com/robots.txt`: HTTP 200; `User-agent: *`, `Disallow: /about/`, plus a sitemap. A robots rule is crawler routing metadata, not a license to invoke undocumented application endpoints.
- Shandong Airlines privacy policy: <https://www.sda.cn/friendly/privacyPolicy.html>. It describes browser/device tracking, Cookies and web beacons, but does not grant automated extraction or endpoint reuse rights.
- Shandong Airlines `https://www.sda.cn/robots.txt`: HTTP 404.
- Shandong Airlines `https://flights.sda.cn/robots.txt`: HTTP 200; `User-agent: *`, `Disallow: /updateBrowser.html`. This does not constitute an API or commercial-use license.

## Approval gates still missing

1. Written airline/API owner authorization or a published API license covering server-side automated search and data reuse.
2. Confirmed per-airline endpoint method/path, request parameters, required Cookie/token/channel rules and stable response schema.
3. Controlled rate-limit test with an agreed QPS ceiling and `429/Retry-After` evidence. Repeated probing without permission is not an acceptable way to discover the threshold.
4. Price, cabin and availability fields confirmed from the same real response for every airline.
5. Named business/legal approver and approval record.

Until all gates are present, changing `LICENSE_STATUS` to `APPROVED` would be a false approval. This review is an engineering governance record, not legal advice.
