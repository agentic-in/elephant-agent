import React from "react";

import {SkillHubDetailPage} from "../../../components/skillhub/SkillHubDetailPage";
import {skillHubCatalogById} from "../../../generated/skillhubCatalog";

export default function SkillHubUnslothPage(): React.JSX.Element {
  return <SkillHubDetailPage entry={skillHubCatalogById["unsloth"]} />;
}
