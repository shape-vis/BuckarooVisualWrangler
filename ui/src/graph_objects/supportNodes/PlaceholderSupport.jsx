/**
 * The placeholder kind of supporting sub-node: a note and nothing else. It exists so the whole path -
 * modal, form, record, layout, node - works end to end before the real kinds are designed.
 */

export function PlaceholderConfigForm({value, onChange}) {
    return (
        <label className="support-form-field">
            Note
            <input
                type="text"
                value={value.note ?? ""}
                placeholder="Optional"
                onChange={(event) => onChange({...value, note: event.target.value})}
            />
        </label>
    );
}

export function PlaceholderBody({record}) {
    return <div className="support-node-note">{record.config?.note || "—"}</div>;
}
