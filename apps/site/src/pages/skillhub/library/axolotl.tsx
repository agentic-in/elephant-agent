import React from "react";

import {SkillHubDetailPage} from "../../../components/skillhub/SkillHubDetailPage";
import {skillHubCatalogById} from "../../../generated/skillhubCatalog";

export default function SkillHubAxolotlPage(): React.JSX.Element {
  return <SkillHubDetailPage entry={skillHubCatalogById["axolotl"]} />;
}
