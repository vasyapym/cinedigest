# TMDB image/data use — primary-source research

Date of research: 2026-11-05. Written for the cinedigest Saint Petersburg screenings website (private person, non-commercial, ad-free, static GitHub Pages).

## Sources consulted (all fresh fetches, 2026-11-05)

- https://developer.themoviedb.org/docs/getting-started (page updated 2025-10-08)
- https://developer.themoviedb.org/docs/faq (updated 2025-10-07)
- https://developer.themoviedb.org/docs/authentication-application (updated 2025-10-27)
- https://developer.themoviedb.org/docs/rate-limiting (updated 2025-10-20)
- https://developer.themoviedb.org/docs/image-basics (updated 2025-10-01)
- https://developer.themoviedb.org/reference/configuration-details (updated 2025-10-01, includes specimen `/configuration` response)
- https://www.themoviedb.org/documentation/api/terms-of-use — **API Terms of Use, last updated October 20, 2023** (stated at page bottom)
- https://www.themoviedb.org/terms-of-use — **general site Terms of Use, last updated May 10, 2024**
- https://www.themoviedb.org/about/logos-attribution — Logos & Attribution page
- https://www.themoviedb.org/dmca-policy — DMCA Policy
- https://www.themoviedb.org/api-for-business — commercial API marketing page

Method note: `developer.themoviedb.org` was fetched directly (ReadMe-hosted docs expose clean Markdown via a `.md` URL suffix). `www.themoviedb.org` pages are DNS-sinkholed on this machine (resolve to 127.0.0.1), so the regular fetcher could not reach them — they were fetched fresh with `curl` against live CloudFront IPs obtained via DNS-over-HTTPS, pretending nothing was cached; the returned pages carry footer build `2eee3a4 (11275)` and the terms' own "last updated" dates. `help.themoviedb.org` does not resolve (no A record in DoH) — assumed decommissioned. Web search was unavailable (403), so all substance came from the primary pages above. The API registration form itself (`https://www.themoviedb.org/settings/api`) requires a login and was **not** accessed, per task constraints. Logo SVGs on the logos page are images; text extraction captured the page's textual content and brand colors.

---

## 1. Current API access model

Free, self-service, for non-commercial use with attribution:

> "Our API is free to use for non-commercial purposes as long as you attribute TMDB as the source of the data and/or images." — [FAQ](https://developer.themoviedb.org/docs/faq)

Registration is self-service through the account settings; public docs describe no approval queue, waiting list, or review step (the form itself is login-protected and could not be inspected):

> "To register for an API key, click the [API link](https://www.themoviedb.org/settings/api) from within your account settings page." — [Getting Started](https://developer.themoviedb.org/docs/getting-started)

Agreeing to the terms is part of issuance:

> "Before being issued an API key you will have to agree to our terms of use." — [Getting Started](https://developer.themoviedb.org/docs/getting-started)

Two credentials are issued in account API settings; the current default is a Bearer **API Read Access Token** usable across API v3 and v4:

> "Version 3 is controlled by either a single query parameter, `api_key`, or by using your access token as a `Bearer` token."  /  "under the API settings section, you will see a new token listed called *API Read Access Token*. This token is expected to be sent along as an `Authorization` header." — [Authentication / Application](https://developer.themoviedb.org/docs/authentication-application)

No special rule for personal/hobby projects exists beyond the general conditions (non-commercial + attribution + §1.C restrictions). A commercial tier exists only via a written agreement / sales contact ([FAQ](https://developer.themoviedb.org/docs/faq), [api-for-business](https://www.themoviedb.org/api-for-business)).

## 2. The non-commercial / commercial line, and who decides

The binding text is the [API Terms of Use](https://www.themoviedb.org/documentation/api/terms-of-use) §2.A:

> "The license in Paragraph 1.A above does not permit any commercial use of TMDB, the TMDB APIs, or TMDB Content. Selling, leasing, or sublicensing the TMDB APIs, access to the TMDB APIs, or TMDB Content, or deriving revenues from the use or provision of TMDB, the TMDB APIs, or TMDB Content, for commercial or monetary gain, directly or indirectly, is, for the purposes of these terms and conditions, considered a commercial use and is only permitted under a separate written agreement between You and TMDB. TMDB reserves the right to, in its sole discretion, determine whether Your use is commercial at the time that you apply for the license to use the TMDB APIs. TMDB reserves the right to monitor Your use or Your Application to make or revise its determination."

**Who decides:** TMDB, in its sole discretion, at the time of application and by ongoing monitoring (text above).

The FAQ restates the test in plainer words:

> "A commercial API is for commercial projects and a developer API is for developers. Your project is considered commercial if the primary purpose is to create revenue for the benefit of the owner." — [FAQ](https://developer.themoviedb.org/docs/faq)

The §2.A "common examples" list is entirely revenue-flavoured: charging users a fee; selling an application with TMDB content; "Using TMDB, the TMDB APIs, or TMDB Content on or in connection with a 'destination' website … or for driving traffic or generating revenue for a website … (including from advertising displayed on or by the website…)"; "Operating a website that generates revenue through charging users for access to content"; ML/AI training datasets (§2.A, [API Terms of Use](https://www.themoviedb.org/documentation/api/terms-of-use)).

A public, non-monetized, ad-free website is **not literally enumerated**. The literal hinge is the word "revenues … directly or indirectly" — nothing in the terms makes "public" or "website" itself commercial factors. Note also the general site [Terms of Use](https://www.themoviedb.org/terms-of-use) §3.A frames the whole Site/Services as "personal, non-commercial use … may not be used in connection with any commercial endeavors … unless expressly authorized by Us in writing", referring back to API TOU §2.A/2.B for API consumers.

"Your Application" scope: the API TOU defines "Application(s)" broadly — "any website, program, service, application, or other product … that accesses TMDB or the TMDB APIs" (§1.C, first bullet, [API Terms of Use](https://www.themoviedb.org/documentation/api/terms-of-use)); a static site fitted with an API-fetched poster list is well within that definition, and as the single registered "person" behind the key, the ("You or Your … any legal entity that employs such individual…") preamble binds the individual account holder.

## 3. Attribution requirements — exactly

From [API Terms of Use](https://www.themoviedb.org/documentation/api/terms-of-use) §3 (verbatim):

> "You must use the TMDB logo to identify Your use of TMDB, the TMDB APIs, or TMDB Content. Any use of any TMDB logos in Your Application must be less prominent than the logos or marks that primarily describe or identify Your Application and must make it clear that use of any TMDB logos does not imply any endorsement, certification, or other approval by TMDB. In addition, You must place the following notice prominently in or on Your Application:
>
> "This [website, program, service, application, product] uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.""

So three components: (a) the TMDB logo, from the approved set, (b) subordinate prominence relative to our own branding, (c) the disclaimer notice, verbatim with the bracket resolved ("This website …"), displayed "prominently".

The [FAQ](https://developer.themoviedb.org/docs/faq) adds the placement rule:

> "When attributing TMDB, the attribution must be within your application's "About" or "Credits" type section."

and points to the approved logo set:

> "When using a TMDB logo, we require you to use [one of our approved logos](https://www.themoviedb.org/about/logos-attribution)."

The [Logos & Attribution page](https://www.themoviedb.org/about/logos-attribution) opens:

> "As per our terms of use, every application that uses our data or images is required to properly attribute TMDB as the source."

and lists the approved SVG logos (Primary full / Primary short / Primary long / Alt long / Alt short, blue) with brand colors `#0d253f`, `#01b4e4`, `#90cea1`. Branding rules from the [FAQ](https://developer.themoviedb.org/docs/faq): the logo "should not be modified in color, aspect ratio, flipped or rotated except where otherwise noted"; naming must be "TMDB" or "The Movie Database"; links should point to `https://www.themoviedb.org`.

**Less-prominent rule:** yes, literal — the TMDB mark must be less prominent than the logo/mark that primarily describes our application (API TOU §3; FAQ "the logo or mark that primarily describes the application").

**No-logo case:** the terms assume a logo ("You must use the TMDB logo…") and nowhere in the fetched primary pages is a text-only fallback or a "if no logo is shown" rule addressed. Flagged as not found; if we ever showed attribution without the logo we would be outside the literal §3 requirement.

A page footer with logo + notice qualifies as an "About/Credits type section" per the FAQ wording, where a static site has no dedicated About page.

## 4. Images specifically (image.tmdb.org)

**URL construction:** the [image Basics](https://developer.themoviedb.org/docs/image-basics) doc defines URLs as `base_url` + `file_size` + `file_path`, with an example URL: `https://image.tmdb.org/t/p/w500/1E5baAaEse26fej7uHcjOgEE2t2.jpg`. Sizes are whatever a type's list contains — the `/configuration` specimen ([reference page](https://developer.themoviedb.org/reference/configuration-details)) shows `poster_sizes: ["w92","w154","w185","w342","w500","w780","original"]` (`w92` and `w185` are valid options), `backdrop_sizes`, `logo_sizes`, `profile_sizes`, `still_sizes`. SVGs must be called at `original` ("For SVG's, you should call the original image size since we don't resize them"). **No key is required in the image URL.**

**Hotlinking / local copies:** none of the primary pages fetched states a hotlink-or-local rule explicitly. What the terms do say, in [API Terms of Use](https://www.themoviedb.org/documentation/api/terms-of-use) §1.C Restrictions (verbatim, relevant bullets):

> "• Cache, for longer than 6 months, any information obtained through or from TMDB or the TMDB APIs."

> "• Make derivatives of the TMDB APIs or TMDB Content."

> "• Use TMDB as an image hosting service for banner advertisements, graphics, etc."

**Caching / data retention (the literal clause):** six months, for *any* information obtained through TMDB, which covers poster `file_path`s — their own examples include image path resolution. **No "must refresh data" obligation exists in the current text**; the only freshness rule is the 6-month cache cap. Note the deletion tail after termination (§1.D):

> "If TMDB terminates Your license, or You terminate your license, You must immediately cease all use of the TMDB APIs, TMDB Content, and any TMDB API key(s), and you must promptly delete or otherwise purge all TMDB Content, including any cached content."

So a JSON of resolved poster paths is a permitted cache but must not silently outlive 6 months (i.e. paths committed to the repo need a re-check/re-resolution at least every 6 months to stay within the clause; also practical because TMDB replaces artwork, in which case old paths 404 — though nothing in the terms guarantees the CDN serves any given poster forever, and nothing promises NOT to delete posters either).

For confidently identified films, the poster cache additionally stores production-country names obtained from TMDB movie details, together with their retrieval date and TMDB provenance. These fields share the existing cache-entry refresh and pruning lifecycle; they do not extend metadata or poster-byte retention. Details retrieval is bounded by the same per-run film-admission limit, while poster downloads retain their separate limits; failed or unavailable country data is not inferred from search results.

The [FAQ](https://developer.themoviedb.org/docs/faq) "API legal notice" confirms the rights baseline:

> "We do not claim ownership of any of the images or data in the API. We comply with the Digital Millennium Copyright Act (DMCA) and expeditiously remove infringing content when properly notified. Any data and/or images you upload you expressly grant us a license to use. You are prohibited from using the images and/or data in connection with libelous, defamatory, obscene, pornographic, abusive or otherwise offensive content."

**Resizing/watermarks:** no size-selection is a violation (choosing `w185` is the built-in mechanism), but because §1.C bans "derivatives of … TMDB Content", overlaying text/watermarks/borders programmatically on the artwork is, on the straightforward reading, a derivative and so not covered (judgment, flagged as such). No watermark rule demanded of us is found anywhere.

## 5. Rate limits (developer / free tier)

From the [Rate Limiting](https://developer.themoviedb.org/docs/rate-limiting) page:

> "As of December 16, 2019, we have disabled the original API rate limiting (40 requests every 10 seconds.)"

> "While our legacy rate limits have been disabled for some time, we do still have some upper limits to help mitigate needlessly high bulk scraping. They sit somewhere in the 40 requests per second range. This limit could change at any time so be respectful of the service we have built and respect the `429` if you receive one."

**No per-day / monthly cap is stated** in primary docs; only the ~40 req/s upper bound and honoring `429`. No SLA: "We do not currently provide an SLA." — [FAQ](https://developer.themoviedb.org/docs/faq).

## 6. Explicitly forbidden things relevant to our design

From [API Terms of Use](https://www.themoviedb.org/documentation/api/terms-of-use) §1.C:

- hiding/impairing: "Attempt to cloak or conceal Your identity …", and no Applications that "(i) uses an excessive amount of bandwidth, (ii) degrade or impair …, or (iii) otherwise adversely impacts the stability of TMDB…"
- **caching beyond 6 months** ("Cache, for longer than 6 months, any information obtained through or from TMDB…"; also §1.D termination → purge cached content).
- **derivative works** ("Make derivatives of the TMDB APIs or TMDB Content").
- **using TMDB as an image host** for "banner advertisements, graphics, etc." — i.e. don't route our own non-TMDB banners/graphics through image.tmdb.org.
- commercial derivation ("Sell, lease, or sublicense … or derive revenues from the use or provision of TMDB … except as expressly permitted in a written agreement"), and misleading source-of-origin ("Use the TMDB APIs in a manner that is confusing or misleading as to the source or origin of Your Application" — mitigated by visible attribution).
- ML/AI training with TMDB content (also §2.A) — irrelevant to this site but worth remembering for any future feature.

From [the general Terms of Use](https://www.themoviedb.org/terms-of-use) (site scraping / bulk redistribution, §3.B and §5):

> "You must not directly, or indirectly, copy, download, reproduce, duplicate, archive, scrape, distribute, upload, publish, modify, translate, broadcast, perform, display, sell, transfer, rent, sub-license, transmit or retransmit other users' Contributions or the Materials except as expressly permitted in Section 4.A for your personal, non-commercial purposes…"

> "You further agree not to access this Site by any means other than through the interface that we provide, unless otherwise specifically authorized by us in a separate written agreement." (§5)

i.e. no scraping of the website themselves and no bulk redistribution of others' Contributions; the API is the sanctioned interface.

**Attribution removal** is prohibited: "You must not, directly or indirectly, remove, alter, bypass, avoid, interfere with, or circumvent any copyright, trademark, or other proprietary notices …" (TOU §3.B) and mandated by API TOU §3 as above.

## 7. Verdict (owner-judgment, not law)

**Your judgment:** the pattern as described — private person, non-commercial, no ads, no fees, public static website — sits, on the literal text, inside the free developer (non-commercial) tier of the API Terms of Use: nothing in §2's enumeration describes a revenue-free informational listing, and the FAQ's test ("primary purpose is to create revenue") is not met. TMDB keeps sole discretion to revise the determination, so it's an ongoing condition, not a certificate.

**Conditions to stay inside it (owner checklist):**

1. Register an API key / read-access token in our own account, on behalf of this project only (the key is personal, non-transferable: API TOU §10.E "The rights and obligations … are personal to you and may not be transferred by you…").
2. Keep the site monetization-free — no ads, no paid access, no affiliate/revenue-driving elements (§2.A).
3. Attribution: TMDB logo (approved set) + the verbatim notice "This website uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB." prominently (footer qualifies as an About/Credits-type section), with the TMDB mark less prominent than the site's own branding (API TOU §3, FAQ).
4. Don't cache TMDB data (incl. poster paths) longer than **6 months** without a re-fetch (API TOU §1.C); refresh the JSON cache at least every 6 months.
5. Don't mutate/overlay/watermark the artwork (avoids the §1.C derivative-work clause — judgment call).
6. Don't use image.tmdb.org to host anything of ours that isn't TMDB content (§1.C).
7. Don't scrape themoviedb.org pages; use the API only (TOU §5).
8. Keep traffic well below ~40 req/s and respect `429` (rate-limits page).

**Not addressed by TMDB sources (acknowledged limits):**

- Original artwork rights: TMDB explicitly does not own or license posters ("We do not claim ownership of any of the images or data in the API", FAQ). Distributors/studios hold those rights, and whether displaying distributor artwork thumbnails on our site is permissible is a matter outside anything TMDB can or does grant — beyond the scope of TMDB primary docs.
- Hotlink vs local-copy is literally unregulated (only the 6-month cache and the image-hosting-for-our-own-graphics rule bear on it); no term here endorses one over the other.
- The terms don't define an SLA-grade guarantee of any content surviving; TMDB may purge content at termination or upon removal requests.

## 8. Takedowns / complaints about user-submitted artwork

Found. TMDB maintains a [DMCA Policy](https://www.themoviedb.org/dmca-policy) and a dedicated online takedown form (`https://www.themoviedb.org/dmca-takedown`; email `dmca@themoviedb.org`), including counter-notice procedure and a "repeat infringer" rule ("TMDB will define a 'repeat infringer' as any person or entity about whom TMDB has received three or more valid DMCA Notices."). The [FAQ](https://developer.themoviedb.org/docs/faq) adds the API-level statement quoted in §4 ("We comply with the DMCA and expeditiously remove infringing content when properly notified."). Practical meaning for us: artwork can be removed from TMDB by rightsholders, which points back to keeping our cache fresh (and is also the avenue if anyone ever mistakenly targets artwork as ours — unrelated to TMDB's site).

---

## Decision inputs (owner summary)

**Go, with conditions.** The published model covers a non-commercial, ad-free, public site on the free developer API. Conditions:

- [ ] API key + Bearer read token registered under the owner's own account; no transfer/sub-licensing.
- [ ] Verbatim attribution notice + approved TMDB logo in the page footer, TMDB mark less prominent than the site's own branding; link to https://www.themoviedb.org.
- [ ] No ads/monetization ever (the needing-to-check condition — TMDB has sole discretion and revenue "directly or indirectly").
- [ ] JSON poster-path cache re-resolved at least every 6 months (no >6-month TMDB-data caching).
- [ ] Artwork served as-is (no watermarks/overlays); no image.hot-link hosting of our own graphics; no scraping of themoviedb.org.
- [ ] Respect ~40 req/s and 429; no matter — a once-per-film resolution at build time is far lower.
- [ ] Accept that poster artwork rights belong to distributors and are not warranted by TMDB's terms; this is the acknowledged unresolvable gap.
