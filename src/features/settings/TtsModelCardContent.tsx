import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { TtsAssetCard, TtsCatalogItem, TtsRegistry } from "../../types";
import { ModelBoardCardFooter } from "./ModelBoardCardFooter";
import { formatSize } from "./TtsModelDialog";

function HorizontallyFittedText({ enabled, text, horizontalPadding = 0, variable }: { enabled: boolean; text: string; horizontalPadding?: number; variable: "--tts-author-scale" | "--tts-line-scale" }) {
  const contentRef = useRef<HTMLSpanElement>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const content = contentRef.current;
    const slot = content?.parentElement;
    if (!enabled || !slot || !content) {
      setScale(1);
      return;
    }
    const measure = () => setScale(Math.min(1, Math.max(0, slot.clientWidth - horizontalPadding) / content.scrollWidth));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(slot);
    observer.observe(content);
    return () => observer.disconnect();
  }, [enabled, horizontalPadding, text]);
  return (
    <span ref={contentRef} style={{ [variable]: scale } as CSSProperties}>
      {text}
    </span>
  );
}

export function ModelMetadataTags({ card, compressAuthor = false }: { card: Pick<TtsAssetCard, "author" | "releasedAt"> | Pick<TtsCatalogItem, "author" | "releasedAt">; compressAuthor?: boolean }) {
  if (!card.author && !card.releasedAt) return null;
  return (
    <span className={`tts-model-metadata-tags${compressAuthor ? " is-compressed" : ""}`}>
      {card.author && (
        <small className="model-card-tag is-neutral tts-model-author-tag" aria-label={`作者：${card.author}`}>
          <HorizontallyFittedText enabled={compressAuthor} text={card.author} horizontalPadding={14} variable="--tts-author-scale" />
        </small>
      )}
      {card.releasedAt && (
        <small className="model-card-tag is-neutral tts-model-release-tag" aria-label={`リリース日：${card.releasedAt}`}>
          {card.releasedAt}
        </small>
      )}
    </span>
  );
}

export function TtsCardContent({ card, registry, isDefault, compressMetadata = false }: { card: TtsAssetCard; registry: TtsRegistry; isDefault: boolean; compressMetadata?: boolean }) {
  const offline = card.libraryId && !registry.libraries.find((item) => item.id === card.libraryId)?.available;
  const activeVariant = card.installedVariants?.find((variant) => variant.id === card.activeVariantId);
  const metadata = [card.generation, activeVariant?.precision, formatSize(activeVariant?.diskBytes ?? card.diskBytes)].filter(Boolean).join(" · ");
  return (
    <>
      <span className="model-card-heading">
        <strong className={compressMetadata ? "tts-model-fit-line" : undefined}>
          <HorizontallyFittedText enabled={compressMetadata} text={card.displayName} variable="--tts-line-scale" />
        </strong>
      </span>
      <span className="model-card-body">
        <ModelMetadataTags card={card} compressAuthor={compressMetadata} />
        {offline && <span className="warning-text">接続先が見つかりません</span>}
        {card.tagline && (
          <span className={`tts-model-tagline${compressMetadata ? " tts-model-fit-line" : ""}`}>
            <HorizontallyFittedText enabled={compressMetadata} text={card.tagline} variable="--tts-line-scale" />
          </span>
        )}
        {!compressMetadata && card.notice && <small className="tts-selected-model-notice">{card.notice}</small>}
      </span>
      <ModelBoardCardFooter isDefault={isDefault} metadata={metadata} />
    </>
  );
}
