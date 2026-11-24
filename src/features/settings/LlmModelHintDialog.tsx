import { useState } from "react";
import { openExternal } from "../../api";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import ollamaSignInImage from "../../assets/llm-guide/ollama-sign-in.png";
import ollamaDownloadImage from "../../assets/llm-guide/ollama-download.png";
import scenaOllamaModelImage from "../../assets/llm-guide/scena-ollama-model.png";

const OLLAMA_DOWNLOAD_URL = "https://ollama.com/download";
const OLLAMA_SIGN_IN_URL = "https://ollama.com/signin";
const GEMMA_MODEL_URL = "https://ollama.com/library/gemma4:31b-cloud";

type PreviewImage = { src: string; alt: string; title: string };

function HintThumbnail({ image, onOpen }: { image: PreviewImage; onOpen: (image: PreviewImage) => void }) {
  return (
    <button type="button" className="llm-hint-picture-button" aria-label={`${image.title}を拡大表示`} onClick={() => onOpen(image)}>
      <img className="llm-hint-picture" src={image.src} alt={image.alt} />
    </button>
  );
}

function HintImagePreview({ image, onClose }: { image: PreviewImage; onClose: () => void }) {
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal llm-hint-image-dialog" role="dialog" aria-modal="true" aria-labelledby="llm-hint-image-title">
        <DialogHeader title={image.title} titleId="llm-hint-image-title" />
        <button type="button" className="llm-hint-image-preview" aria-label="画像を閉じる" onClick={onClose}>
          <img src={image.src} alt={image.alt} />
        </button>
      </section>
    </ModalBackdrop>
  );
}

export function LlmModelHintDialog({ onClose }: { onClose: () => void }) {
  const [preview, setPreview] = useState<PreviewImage | null>(null);
  const signInImage = { src: ollamaSignInImage, alt: "Ollamaのサインイン画面。メール、Google、GitHubから登録またはサインインできます。", title: "Ollamaの登録画面" };
  const downloadImage = { src: ollamaDownloadImage, alt: "Ollamaのダウンロード画面。macOS、Linux、Windowsを選べます。", title: "Ollamaのダウンロード画面" };
  const modelImage = { src: scenaOllamaModelImage, alt: "SCENAの接続先追加画面で、Ollamaとgemma4:31b-cloudを指定した状態。", title: "SCENAのOllama接続設定" };
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal llm-model-hint-dialog" role="dialog" aria-modal="true" aria-labelledby="llm-model-hint-title">
        <DialogHeader eyebrow="LLM GUIDE" title="LLMモデルを使うヒント" titleId="llm-model-hint-title" description="Ollama Cloudなら、PC単体では動かしにくい大規模モデルをクラウド側の計算資源で高速に利用できます。" />
        <div className="llm-hint-free-tier" role="note" aria-label="Ollamaの無料利用枠">
          <div className="llm-hint-free-tier-heading">
            <span aria-hidden="true">✦</span>
            <div>
              <small>START FOR FREE</small>
              <strong>無料枠で、SCENAの便利なLLM機能をしっかり試せます</strong>
            </div>
          </div>
          <p>
            毎月更新されるスターター利用枠があるため、<code>gemma4:31b-cloud</code> を使って、実際の制作フローの中で次の機能を試しやすくなっています。
          </p>
          <ul>
            <li>台本の作成・書き直し</li>
            <li>台詞の演出やキャスト設定の提案</li>
            <li>Voice Designの相談</li>
          </ul>
          <small>実際に使える回数は、入力の長さや利用する機能によって変わります。無料枠の量や対象モデルは変更される場合があります。</small>
        </div>
        <div className="llm-hint-notice" role="note">
          <strong>SCENAとは別の外部サービスです</strong>
          <p>OllamaおよびOllama Cloudは、irodori SCENAの提供・運営元とは関係ありません。利用にはOllama側のアカウント、利用規約、料金、プライバシーポリシーが適用されます。クラウドモデルでは、SCENAから送った台本や指示がOllamaのサービスへ送信されます。</p>
        </div>
        <div className="llm-hint-steps">
          <article>
            <HintThumbnail image={signInImage} onOpen={setPreview} />
            <div>
              <span className="llm-hint-step-number">1</span>
              <h3>Ollamaに登録する</h3>
              <p>Ollamaのサイトでアカウントを作成します。すでにアカウントがある場合はサインインしてください。</p>
              <button type="button" className="secondary" onClick={() => void openExternal(OLLAMA_SIGN_IN_URL)}>
                Ollamaの登録ページを開く
              </button>
            </div>
          </article>
          <article>
            <HintThumbnail image={downloadImage} onOpen={setPreview} />
            <div>
              <span className="llm-hint-step-number">2</span>
              <h3>Ollamaアプリを導入する</h3>
              <p>macOSまたはWindows用アプリをOllama公式サイトからダウンロードし、アプリの設定からサインインします。</p>
              <span className="llm-hint-links">
                <button type="button" className="secondary" onClick={() => void openExternal(OLLAMA_DOWNLOAD_URL)}>
                  Ollamaをダウンロード
                </button>
              </span>
            </div>
          </article>
          <article>
            <HintThumbnail image={modelImage} onOpen={setPreview} />
            <div>
              <span className="llm-hint-step-number">3</span>
              <h3>SCENAへ接続する</h3>
              <p>
                設定の「LLMモデル」から「接続先を追加」を選び、種類を「Ollama」、URLを既定のままにして「モデルを確認」を押します。「API Keyを設定（任意）」はオフのままで構いません。モデル欄へ <code>gemma4:31b-cloud</code> を直接入力し、「このモデルを追加」を押します。
              </p>
              <span className="llm-hint-links">
                <button type="button" className="quiet-button" onClick={() => void openExternal(GEMMA_MODEL_URL)}>
                  モデル情報
                </button>
              </span>
            </div>
          </article>
        </div>
        <DialogFooter>
          <button type="button" className="secondary" onClick={onClose}>
            閉じる
          </button>
        </DialogFooter>
        {preview && <HintImagePreview image={preview} onClose={() => setPreview(null)} />}
      </section>
    </ModalBackdrop>
  );
}
