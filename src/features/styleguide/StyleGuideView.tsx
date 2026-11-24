import "../../styles/styleguide.css";
import { FoundationCatalog } from "./FoundationCatalog";
import { StyleGuideIndex } from "./StyleGuideIndex";
import { closeStyleGuide } from "./styleGuideNavigation";
import { ControlsSection, CustomButtonsSection, InsertControlsSection, SurfacesSection } from "./StyleGuideBasicSections";
import { DialogsSection, FormsSection, ModelsSection } from "./StyleGuideFormSections";
import { Section } from "./StyleGuideParts";
import { AuditSection, FeedbackSection } from "./StyleGuideStateSections";

function StyleGuideHero() {
  return (
    <header className="styleguide-hero">
      <div>
        <p className="eyebrow">DEVELOPMENT</p>
        <h1>SCENA スタイルガイド</h1>
        <p>ここは本アプリと同じCSSを読む開発用カタログです。スタイルシートやトークンを編集すると、このページと本アプリの両方へ反映されます。</p>
      </div>
      <button className="secondary" type="button" onClick={closeStyleGuide}>
        アプリへ戻る
      </button>
    </header>
  );
}

export function StyleGuideView() {
  return (
    <main className="styleguide" aria-label="SCENA スタイルガイド">
      <StyleGuideHero />

      <StyleGuideIndex />

      <Section id="foundations" title="デザインの基礎" source="tokens.css">
        <p className="subtle">本アプリが共通で使う色、文字、余白、角丸を一覧で確認します。</p>
        <FoundationCatalog />
      </Section>

      <SurfacesSection />
      <ControlsSection />
      <CustomButtonsSection />
      <InsertControlsSection />
      <FormsSection />
      <ModelsSection />
      <DialogsSection />
      <FeedbackSection />
      <AuditSection />
    </main>
  );
}
