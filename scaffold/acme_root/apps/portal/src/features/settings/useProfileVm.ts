import { useState } from "react";
import { errorMessage } from "../../app/errorMessage";
import { THEME_CHOICES } from "../../app/themeModel";
import { useMe, useUpdateMe } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { usePreferencesStore } from "../../store/preferences";
import { checkDisplayName } from "./settingsModel";

/** Personal › Profile: the name every org shows for the person, and the
 * theme this browser draws. The name field starts from the saved name and
 * keeps what is typed until it is saved. */
export function useProfileVm() {
  const me = useMe();
  const update = useUpdateMe();
  const notify = useNoticesStore((s) => s.notify);
  const theme = usePreferencesStore((s) => s.theme);
  const setTheme = usePreferencesStore((s) => s.setTheme);
  const [typed, setTyped] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const saved = me.data?.user.display_name ?? "";
  const name = typed ?? saved;

  const save = async () => {
    const refused = checkDisplayName(name);
    setProblem(refused);
    if (refused) return;
    try {
      await update.mutateAsync({ display_name: name.trim() });
      setTyped(null);
    } catch (caught) {
      notify(errorMessage(caught, "The name was not saved."));
    }
  };

  return {
    me: me.data,
    error: me.error,
    email: me.data?.user.email ?? "",
    name,
    setName: (value: string) => {
      setTyped(value);
      setProblem(null);
    },
    changed: typed !== null && typed.trim() !== saved,
    problem,
    save,
    saving: update.isPending,
    theme,
    themes: THEME_CHOICES,
    setTheme,
  };
}

export type ProfileVm = ReturnType<typeof useProfileVm>;
