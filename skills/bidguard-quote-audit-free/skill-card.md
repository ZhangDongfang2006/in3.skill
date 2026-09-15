## Description:

A free local bid-quote pre-check that flags line-item arithmetic mismatches and missing quantity, unit-price, or total-amount fields without registration, payment, or API keys.

This skill is ready for commercial/non-commercial use.

## Publisher:

[chenqg618](https://clawhub.ai/user/chenqg618)

### License/Terms of Use:

MIT-0

## Use Case:

Bid preparers, procurement reviewers, and developers use this skill to locally pre-check bid quote line items for arithmetic mismatches and missing quantity, unit-price, or total-amount fields before submission. It is a pre-check aid, not an official bid evaluation or scoring decision.

### Deployment Geography for Use:

Global

## Known Risks and Mitigations:

Risk: Bid documents may contain sensitive commercial data.

Mitigation: Run the checker locally and provide only files intended for the Node script to read; the security evidence reports no network or credential behavior.

Risk: The free release covers only line-item arithmetic checks and missing-field prompts, so it can miss broader bid compliance issues.

Mitigation: Review the listed withheld checks and use qualified human review for official bid evaluation decisions.

Risk: Insufficient or poorly structured input can prevent valid checking.

Mitigation: Treat an insufficient-input result as no conclusion and provide complete quote text or structured line items before relying on the output.

## Reference(s):

- [ClawHub skill page](https://clawhub.ai/chenqg618/skills/bidguard-quote-audit-free)
- [Free web checker](https://www.tokendidi.cn/check)
- [AI 核对工具铺](https://skillpay.alipay.com/public/tokendidi)

## Skill Output:

**Output Type(s):** [Text, JSON, Guidance]

**Output Format:** [Plain text report or JSON result from a local Node.js checker]

**Output Parameters:** [1D]

**Other Properties Related to Output:** [Reports executed and withheld checks; exits with code 3 and no conclusion when input is insufficient.]

## Skill Version(s):

1.0.8 (source: server release metadata and SKILL.md frontmatter)

## Ethical Considerations:

Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment.
