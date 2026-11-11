# Recipe Organizer

Saves recipes from Instagram/TikTok links, extracting ingredients and
directions automatically where the platform allows it. Each person signs
up with an email and password and sees only their own recipes and
categories.

## Important: how Instagram and TikTok are actually handled differs

This isn't a stylistic choice - it reflects two hard, real constraints
I found by checking Meta's and TikTok's current API documentation
before building this, not general knowledge:

**TikTok**: fully automatic. TikTok's public oEmbed endpoint
(`tiktok.com/oembed`) returns the video's actual caption text in a
`title` field, no authentication needed, and this is a documented,
sanctioned use case. Paste a TikTok link and the caption is fetched and
extracted automatically.

**Instagram**: cannot be automatic, for two independent reasons, either
one alone would block it:
1. Instagram's oEmbed response does not include caption text at all -
   it only returns an embeddable HTML widget (author name, thumbnail,
   etc.), not the post's description.
2. Even if it did, Meta's oEmbed terms explicitly prohibit using that
   data for anything beyond displaying the post - they specifically
   call out "extracting, or persisting the metadata and content" as
   forbidden.

So for Instagram links, you paste the link, then copy the caption text
from the app yourself and paste it in - the AI extraction still does the
work of pulling out ingredients and steps, it just can't fetch the
caption on its own. This was confirmed with you directly before
building rather than assumed.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# set ANTHROPIC_API_KEY - required, there's no automatic-extraction
# fallback without it (manual entry always still works)
python src/app.py      # localhost:5050
```

## Running the tests

```bash
pytest tests/
```
55 tests, covering URL/platform detection, TikTok oEmbed parsing
(caption and thumbnail), AI extraction response parsing, recipe storage
lifecycle, and category storage (including the safety behavior:
deleting a category unassigns its recipes rather than deleting them,
and category names must be unique). A live simulation also confirmed
the schema migration preserves existing recipes when the new
category/thumbnail columns are added to a database created before this
update.

**Confirmed working end-to-end** against the real running server: adding
links, submitting captions, listing, viewing, manually editing a failed
extraction, deleting, and bulk import all verified with real HTTP
requests, not just unit tests in isolation.

## What I could not verify from here

- **TikTok's live oEmbed response** - tiktok.com isn't reachable from my
  sandbox (confirmed with a real request, got blocked). The parsing
  logic is tested against a fixture matching a real oEmbed response
  shape (confirmed via a third-party TikTok API wrapper's documented
  output), and the error-handling path is confirmed working against a
  real HTTP failure - but the actual live fetch needs you to test it.
- **AI extraction accuracy** - no ANTHROPIC_API_KEY is set in my
  sandbox, so I confirmed the graceful-failure path (clear error, link
  preserved) but not what a real extraction actually produces for a
  real caption. The parsing logic itself is thoroughly tested against
  realistic response fixtures.

If either of these behaves differently than expected on your first real
try, tell me the exact error and I'll fix it against real data.

## What it does

1. Add a recipe: paste a link, optionally pick a category. TikTok
   auto-fetches the caption and cover image and extracts. Instagram asks
   you to paste the caption, then extracts from that (no auto-thumbnail
   for Instagram - there's no sanctioned way to fetch one, same
   constraint as the caption).
2. Bulk import: upload your Instagram/TikTok data export file.
3. No recipe found: the recipe is saved (not discarded) with a clear
   message, and you can fill in ingredients/directions by hand.
4. Recipe detail page: shows the cover image (when available) at the
   top, ingredients, directions, original caption, edit anything
   manually.
5. Categories: create named categories from the Categories page. Assign
   a category when adding a recipe (from the home page or directly from
   a category's own page). Each category page shows its recipes in a
   full-width 6-column thumbnail grid. Deleting a category unassigns its
   recipes rather than deleting them.

## About the thumbnail

TikTok's oEmbed response includes a `thumbnail_url` - the video's own
cover image, which TikTok itself generates (not necessarily literally
frame zero, but the designated cover). This is what's shown, since
actually downloading and processing the video file to extract a
specific frame would be both a much bigger technical lift and murkier
ToS territory than using a field TikTok already provides for exactly
this purpose. Instagram recipes have no thumbnail, for the same reason
they have no auto-fetched caption.

## Roadmap

- A downloadable/printable format for a single recipe (mirroring the
  Meal Planner's screenshot/print view)
- Search/filter across saved recipes
- Tagging or categorizing recipes (cuisine, meal type)
