# Anjan Chatterjee — Writing Rules

Anjan's prose discipline, distilled into 21 rules. The first 12 are the lab's
standing review rules (global patterns, evidence/interpretation, uncertainty).
Rules 13–20 add the sentence-level craft Anjan insists on: plain words, active
verbs, no filler, payoff over repetition. Rule 21 is a standing correction:
methods, not methodology. Use these for every manuscript the lab touches.

In practice: make the claim strong, the mechanism cautious, the prose clean,
and the contribution impossible to miss.

---

## The 20 rules

1. **Start with the phenomenon, not the theory.** Open with what the reader can
   picture: masks, faces, gaze, scale, bodily response, viewer position, ritual
   space. Bring theory in only after the phenomenon is clear.

2. **Make the first sentence plain.** Do not begin with a dense theoretical
   claim. A reader should know the object, the problem, and the stakes within
   the first few lines.

3. **Do not overclaim mechanism.** Archaeology/behavior is *consistent with*
   perceptual/affective systems; it does not *prove* a neural mechanism. Define
   the problem before naming the framework (ENO, neuroaesthetics, ontology,
   predictive processing). First show the gap, then bring in the framework.
   USE: may have recruited · likely intensified · is consistent with · helps
   explain · offers a plausible account of · would have made available.
   AVOID: proves · demonstrates that [builders] knew · caused · directly
   activated · hardwired.

4. **Separate evidence from interpretation.** Keep the chain clean: (1) what
   is documented? (2) what is perceptually salient? (3) what does research make
   plausible? (4) what remains interpretive/speculative? Say what the material
   record shows, then say what you infer. Do not make the inference sound like
   a directly observed fact. The primary evidence carries the claim first;
   neuroscience sharpens the interpretation, it does not replace the evidence.

5. **Prefer convergence over single-study claims.** Several weak-to-moderate
   converging lines (monumentality, frontal symmetry, elevated placement,
   facial configuration, restricted viewing, ritual-political setting) beat
   one strong single-effect claim. Do not lean on one gaze, face, or
   neuroaesthetic study as if it proves the argument.

6. **Keep global patterns primary.** Report global/structural results before
   local/node-level ones. Use global structure, bootstrap intervals, and
   convergence patterns as the main result; treat specific node centrality and
   fine local effects as exploratory unless the sample is large and stable.

7. **Use the sequence: observation → mechanism → implication.** Example: the
   masks are frontal and oversized → frontal faces and gaze-like patterns
   recruit attention and social perception → this helps explain how masks acted
   as powerful ritual presences.

8. **Cut inflated language.** Prefer clean, direct prose over theoretical
   excess. Cut phrases that sound grand but vague — "profoundly transformative,"
   "deeply entangled," "radically reconfigures," "liminally embodied" — unless
   you explain exactly what changes, where, and how.
   Replace: "These masks instantiate an ontologically charged neuroaesthetic
   apparatus through which perceptual salience mediates cosmopolitical
   presence."
   With: "These masks joined perceptual force to cosmological meaning. Their
   scale, frontal faces, and placement helped make sacred authority visible
   and felt."

9. **Do not let the cultural material sound like decoration.** Don't reduce
   culture to an example of a universal brain response. "Universal perceptual
   tendencies do not explain the masks by themselves. They help explain why
   culturally specific beings, places, and powers could become forceful in
   experience."

10. **Make the contribution sayable in one sentence.** For the Maya masks
    paper: "Monumental Maya masks worked because they joined culturally specific
    ideas of divine presence with perceptual features — frontal faces, scale,
    gaze-like organization — that made that presence compelling in embodied
    experience."

11. **Use modest, testable language** that could survive hostile review:
    specific enough to test, modest enough to defend. Not "ENO explains Maya
    ritual experience" but "ENO offers a way to describe how built forms could
    organize attention, affect, and culturally learned expectations in ritual
    settings."

12. **Let the reader see the analytic steps.** Paragraph shape: first sentence
    = concrete claim; middle = evidence and reasoning; final = interpretive
    payoff. One main idea per paragraph — establish the object, explain the
    mechanism, locate the meaning, or state the payoff. Do not mix all four.

13. **Make uncertainty visible.** Strong papers do not hide uncertainty. They
    mark where evidence ends and interpretation begins. Put uncertainty into the
    prose — inside the claim, not as a trailing caveat. e.g., "At this corpus
    size, node-level centrality should be treated as exploratory. The more
    stable result is the repeated convergence of sensory, affective, and
    interpretive features around the same experiential episodes."

14. **Keep interdisciplinary readers in mind.** Archaeologists should not feel
    trapped in neuroscience jargon. Neuroscientists should understand the
    cultural specificity. Anthropologists should see that the argument is not
    reducing Maya religion to brain mechanisms.

15. **Use concrete examples before abstraction.** Discuss Cerros, Kohunlich,
    El Mirador, mask façades, viewer movement, scale, and frontal faces before
    broader claims about affective technologies or embodied neuro-ontology.

16. **Use simple words when possible.** "Use" over "utilize." "Show" over
    "demonstrate" when the claim is simple. "Help explain" over "provides a
    novel explanatory framework for."

17. **Prefer verbs over nouns.** "Masks directed attention" is better than
    "the masks produced an attentional orientation." "Viewers encountered
    faces" is better than "viewer-face encounter dynamics occurred."

18. **Cut filler phrases.** Remove: "It is important to note that," "This
    paper argues that," "In many ways," "deeply," "complexly," "richly,"
    "within the context of."

19. **Use active voice except where passive fits Methods or Results.** "Maya
    builders placed frontal masks on temple façades" is stronger than "frontal
    masks were placed on temple façades."

20. **End paragraphs with payoff, not repetition.** The last sentence should
    move the argument forward, not restate the topic sentence. Do not let
    citations replace argument — citations support claims, but the logic still
    needs to be visible in your prose.

21. **Use "methods," not "methodology."** "Methods" names the specific
    techniques you used. "Methodology" names the study of methods as a field —
    almost never what a paper actually means. Write "we used these methods";
    reserve "methodology" for a paper that is itself about methods as a subject.
    This is one of Anjan's standing corrections: *it's methods, not
    methodology.*

---

## Machine-checkable blocks

These blocks are parsed by `paper-review/scripts/lint_claims.py`. Keep the
`### name` headings exact; the script reads comma-separated term lists below
each. A term on its own line is also fine.

### banned_mechanism_verbs (rule 3) — flag in any claim about cause/mechanism
proves, prove, proven, demonstrates that, caused, causes, directly activated,
hardwired, hard-wired, knew that, makes viewers, forced viewers

### hedge_verbs (rule 3) — preferred replacements
may have recruited, likely intensified, is consistent with, helps explain,
offers a plausible account of, could, plausibly, would have made available

### inflated_markers (rule 8) — flag for tightening
instantiate, ontologically charged, apparatus, mediates, cosmopolitical,
problematize, foregrounds, always-already, interrogate, valorize,
profoundly transformative, deeply entangled, radically reconfigures,
liminally embodied

### filler_phrases (rule 18) — flag for deletion
it is important to note that, this paper argues that, in many ways,
within the context of, it should be noted that, it is worth noting that

### filler_adverbs (rule 18) — flag for tightening
deeply, complexly, richly

### methodology_flag (rule 21) — flag "methodology" where "methods" is meant
methodology

### sentence_length (rule 8 / clarity) — flag sentences over 45 words for tightening
