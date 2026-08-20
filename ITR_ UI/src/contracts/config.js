/* Single source for tenant-level config. Spec header: the demo tenant name is ONE
   config value [A-01]; nothing may hard-code it. Band thresholds are owned by
   calibration [F-077, A-05] and read from here, never inlined. */

export const config = {
  demo_tenant_name: 'Halcyon Foods Group',
  vendor_name: 'Motiveminds ITR',

  // §11.9 / A-14 — tenant default timezone; user override lives in the user menu.
  tenant_timezone: 'Asia/Kolkata',
  tenant_timezone_label: 'IST',

  // §11.2 / A-05 — placeholders owned by calibration; the UI only reads them.
  confidence_bands: { high: 0.85, medium: 0.60 },

  // §10.4 / A-06
  reject_reason_min_chars: 10,

  // NFR budgets the UI degrades against (§11.5)
  budgets_ms: { context_pack: 2000, honest_delay_notice: 2000, stale_after: 60000 },

  // §16 change requests — unratified [OD-3]. Flags, not silent defaults.
  flags: {
    CR_01_tickets_list: true,   // required by the no-dead-end rule (§5.4)
    CR_02_global_search: true,
    CR_03_notifications: true,
  },

  // NFR-33 — a pack spanning fewer systems than this warns in the header.
  min_systems_in_pack: 3,
}

export const TENANT = config.demo_tenant_name
