# {{Campaign Title}}

{{One-line description of the facility/permit action}}

**Comment Deadline: {{Deadline, Month Day, Year}}**

{{N}} posts  •  {{Start Month Day}} – {{End Month Day}}

{{#each posts}}
**Post {{N}} — {{Day}}, {{Month Date}}**

*{{Theme}}. {{Emotional hook}}. {{Audience archetypes}}.*

{{Hook opener}}

{{Body — profile angle blended with research facts}}

{{Optional additional paragraph(s) per the GNOTS model — 2-4 paragraphs total}}

[Image suggestion: {{description of photo/graphic to pair with this post}}]

{{#if final_post}}
Copy and personalize:

*{{Copy/paste comment template}}*
{{/if}}

{{! CTA block — pick ONE shape per post per SKILL.md Step 7's decision logic, not both. }}

{{#if cta_is_hearing}}
**ATTEND THE PUBLIC HEARING:**

**When:** {{hearing date and time}}

**Where:** {{hearing location}}

{{#if comment_period_still_open}}
**Can't make it? Submit a comment by {{DEADLINE}}:** {{portal URL}} / {{email}} — **Reference:** {{permit/docket number}}
{{/if}}
{{else}}
**COMMENT BY {{DEADLINE}} (takes 5 min):**

**Online:** {{portal URL}}

**Email:** {{email}}

**Reference:** {{permit/docket number}}

**Ask {{agency}} to {{ask — e.g. hold a PUBLIC HEARING}}.**

{{#if hearing_pending}}
A hearing has been requested and is not yet scheduled — say so here.
{{/if}}
{{/if}}

{{/each}}

{{Closing share-this line on the final post}}
