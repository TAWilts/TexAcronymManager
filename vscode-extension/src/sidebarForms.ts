import { AcronymCandidate } from "./database";

export interface SidebarAcronymForm {
  plural: boolean;
  label: string;
  long: string;
}

/** Explicit forms stored in acronyms.json. Inferred plurals are intentionally
 * not shown in the sidebar. */
export function sidebarAcronymForms(candidate: AcronymCandidate): SidebarAcronymForm[] {
  const singularLabel = (candidate.short || candidate.key).trim() || candidate.key;
  const forms: SidebarAcronymForm[] = [
    { plural: false, label: singularLabel, long: candidate.long.trim() },
  ];

  const shortPlural = candidate.values.short_plural?.trim() || "";
  const longPlural = candidate.values.long_plural?.trim() || "";
  if (shortPlural || longPlural) {
    forms.push({
      plural: true,
      label: shortPlural || singularLabel,
      long: longPlural,
    });
  }
  return forms;
}
