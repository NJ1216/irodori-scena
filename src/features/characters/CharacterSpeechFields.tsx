import type { CharactersViewModel } from "./useCharactersViewModel";

export function CharacterSpeechFields({ model }: { model: CharactersViewModel }) {
  const { editDetails, setEditDetails, suggestedFieldClass } = model;
  return (
    <section className="character-settings-section underlined-fields" aria-labelledby="speech-settings-heading">
      <h2 id="speech-settings-heading">話し方</h2>
      <div className="character-settings-grid">
        <label>
          一人称
          <input
            className={suggestedFieldClass("firstPerson")}
            value={model.editFirstPerson}
            onChange={(event) => {
              model.clearSuggestedField("firstPerson");
              model.setEditFirstPerson(event.target.value);
            }}
            placeholder="私、あたし"
          />
        </label>
        <label>
          二人称
          <input
            className={suggestedFieldClass("secondPerson")}
            value={model.editSecondPerson}
            onChange={(event) => {
              model.clearSuggestedField("secondPerson");
              model.setEditSecondPerson(event.target.value);
            }}
            placeholder="あなた、君"
          />
        </label>
        <label>
          呼び方の基準
          <select
            className={suggestedFieldClass("defaultAddressBasis")}
            value={editDetails.defaultAddressBasis ?? ""}
            onChange={(event) => {
              model.clearSuggestedField("defaultAddressBasis");
              setEditDetails((details) => ({ ...details, defaultAddressBasis: event.target.value }));
            }}
          >
            <option value="">未設定</option>
            <option>苗字</option>
            <option>名前</option>
            <option>愛称</option>
            <option>役職・肩書</option>
            <option>状況による</option>
          </select>
        </label>
        <label>
          基本の敬称
          <input
            className={suggestedFieldClass("defaultHonorific")}
            value={editDetails.defaultHonorific ?? ""}
            onChange={(event) => {
              model.clearSuggestedField("defaultHonorific");
              setEditDetails((details) => ({ ...details, defaultHonorific: event.target.value }));
            }}
            placeholder="さん、呼び捨て"
          />
        </label>
      </div>
      <label>
        基本の口調
        <textarea
          className={suggestedFieldClass("speechStyle")}
          value={editDetails.speechStyle ?? ""}
          onChange={(event) => {
            model.clearSuggestedField("speechStyle");
            setEditDetails((details) => ({ ...details, speechStyle: event.target.value }));
          }}
        />
      </label>
      <label>
        呼び方の補足
        <textarea
          className={suggestedFieldClass("defaultAddressNote")}
          value={editDetails.defaultAddressNote ?? ""}
          onChange={(event) => {
            model.clearSuggestedField("defaultAddressNote");
            setEditDetails((details) => ({ ...details, defaultAddressNote: event.target.value }));
          }}
        />
      </label>
    </section>
  );
}

export function CharacterRelationFields({ model }: { model: CharactersViewModel }) {
  if (!model.editing) return null;
  const others = model.project.characters.filter((character) => character.id !== model.editing?.id);
  return (
    <section className="character-settings-section underlined-fields" aria-labelledby="character-relations-heading">
      <h2 id="character-relations-heading">人間関係</h2>
      <label>
        その他の人間関係
        <textarea
          className={model.suggestedFieldClass("otherRelationships")}
          value={model.editDetails.otherRelationships ?? ""}
          onChange={(event) => {
            model.clearSuggestedField("otherRelationships");
            model.setEditDetails((details) => ({ ...details, otherRelationships: event.target.value }));
          }}
          placeholder="未登録の人物や集団との関係"
        />
      </label>
      <div className="cast-relations-list">
        {others.map((character) => {
          const relation = model.editDetails.castRelations?.[character.id] ?? {};
          const updateRelation = (field: "address" | "relationship", value: string) => {
            model.clearSuggestedRelation(character.id, field);
            model.setEditDetails((details) => ({
              ...details,
              castRelations: {
                ...details.castRelations,
                [character.id]: { ...details.castRelations?.[character.id], [field]: value },
              },
            }));
          };
          return (
            <div key={character.id} className="cast-relation-card">
              <strong>{character.name}</strong>
              <label>
                呼び方
                <input className={model.profileSuggestionRelations.has(`${character.id}:address`) ? "ai-suggested-value" : ""} value={relation.address ?? ""} onChange={(event) => updateRelation("address", event.target.value)} placeholder="愛称、呼び捨て、役職名など" />
              </label>
              <label>
                関係性
                <textarea className={model.profileSuggestionRelations.has(`${character.id}:relationship`) ? "ai-suggested-value" : ""} value={relation.relationship ?? ""} onChange={(event) => updateRelation("relationship", event.target.value)} placeholder="出会い、現在の距離感、感情、会話時の態度" />
              </label>
            </div>
          );
        })}
      </div>
    </section>
  );
}
