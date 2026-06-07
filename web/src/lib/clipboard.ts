/**
 * Copie de texte robuste, y compris hors contexte sécurisé.
 *
 * `navigator.clipboard` n'existe que dans un "secure context" (HTTPS ou
 * localhost). L'app est souvent servie en HTTP simple sur le LAN — un appel
 * direct lève alors une erreur (ou l'API est carrément absente). On tente donc
 * l'API moderne puis on retombe sur la vieille combine `textarea` + `execCommand`,
 * qui marche en HTTP.
 *
 * Retourne `true` si la copie a réussi, `false` sinon (au lieu de jeter) — le
 * caller peut alors proposer une copie manuelle.
 */
export async function copyText(text: string): Promise<boolean> {
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch {
        // contexte non sécurisé ou permission refusée → on tente le fallback
    }
    try {
        const ta = document.createElement('textarea');
        ta.value = text;
        // Hors écran mais sélectionnable (display:none casserait la sélection).
        ta.style.position = 'fixed';
        ta.style.top = '-9999px';
        ta.setAttribute('readonly', '');
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return ok;
    } catch {
        return false;
    }
}
