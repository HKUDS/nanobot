export interface ComponentSource {
  path: string;
  name: string;
  group: string;
  exports: string[];
  usedBy: string[];
  source: string;
}

export const foundationPath = "webui/src/components/ui/";
