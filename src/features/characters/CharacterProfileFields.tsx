import type { CharacterProfile } from "../../types";
import type { CharactersViewModel } from "./useCharactersViewModel";
import { FieldError } from "../shared/InlineValidation";

type TextField = { key: keyof CharacterProfile; label: string; placeholder?: string };

function TextFields({ model, fields }: { model: CharactersViewModel; fields: TextField[] }) {
  return (
    <div className="character-settings-grid">
      {fields.map(({ key, label, placeholder }) => (
        <label key={key} className="type-field-label">
          {label}
          <input
            className={model.suggestedFieldClass(key)}
            value={(model.editDetails[key] as string | undefined) ?? ""}
            onChange={(event) => {
              model.clearSuggestedField(key);
              model.setEditDetails((details) => ({ ...details, [key]: event.target.value }));
            }}
            placeholder={placeholder}
          />
        </label>
      ))}
    </div>
  );
}

export function CharacterProfileFields({ model }: { model: CharactersViewModel }) {
  return (
    <>
      <section className="character-settings-section underlined-fields" aria-labelledby="character-basic-heading">
        <h2 id="character-basic-heading">基本情報</h2>
        <div className="character-settings-grid">
          <label className="type-field-label">
            表示名
            <input value={model.editName} data-validation-field="editName" aria-invalid={Boolean(model.editValidation.fieldError("editName")) || undefined} onChange={(event) => model.setEditName(event.target.value)} required />
            <FieldError message={model.editValidation.fieldError("editName")} />
          </label>
          <label className="type-field-label">
            愛称
            <input
              className={model.suggestedFieldClass("aliases")}
              value={model.editAliases}
              onChange={(event) => {
                model.clearSuggestedField("aliases");
                model.setEditAliases(event.target.value);
              }}
              placeholder="読点区切りで複数可"
            />
          </label>
        </div>
        <TextFields
          model={model}
          fields={[
            { key: "familyName", label: "苗字", placeholder: "苗字を入力" },
            { key: "familyNameKana", label: "苗字のふりがな", placeholder: "ひらがなで入力" },
            { key: "givenName", label: "名前", placeholder: "名前を入力" },
            { key: "givenNameKana", label: "名前のふりがな", placeholder: "ひらがなで入力" },
            { key: "age", label: "年齢", placeholder: "17歳、高校二年生" },
            { key: "gender", label: "性別" },
            { key: "role", label: "職業・役割", placeholder: "生徒会長" },
          ]}
        />
      </section>
      <section className="character-settings-section underlined-fields" aria-labelledby="character-person-heading">
        <h2 id="character-person-heading">人物像</h2>
        <TextFields
          model={model}
          fields={[
            { key: "skills", label: "特技" },
            { key: "hobbies", label: "趣味" },
            { key: "likes", label: "好きなもの" },
            { key: "dislikes", label: "苦手なもの" },
          ]}
        />
        <label className="type-field-label">
          性格
          <textarea
            className={model.suggestedFieldClass("personality")}
            value={model.editDetails.personality ?? ""}
            onChange={(event) => {
              model.clearSuggestedField("personality");
              model.setEditDetails((details) => ({ ...details, personality: event.target.value }));
            }}
          />
        </label>
        <label className="type-field-label">
          背景・来歴
          <textarea
            className={model.suggestedFieldClass("background")}
            value={model.editDetails.background ?? ""}
            onChange={(event) => {
              model.clearSuggestedField("background");
              model.setEditDetails((details) => ({ ...details, background: event.target.value }));
            }}
          />
        </label>
      </section>
    </>
  );
}

export function CharacterDetailFields({ model }: { model: CharactersViewModel }) {
  return (
    <section className="character-settings-section underlined-fields" aria-labelledby="character-details-heading">
      <h2 id="character-details-heading">詳細情報</h2>
      <TextFields
        model={model}
        fields={[
          { key: "bloodType", label: "血液型" },
          { key: "birthDate", label: "誕生日", placeholder: "4月18日" },
          { key: "birthplace", label: "出身地" },
          { key: "residence", label: "居住地" },
        ]}
      />
    </section>
  );
}
