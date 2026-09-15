// Paste this file into Extensions > Apps Script in the Google Sheet.
// Replace both values before running setupGoogleSheetSync.
const CRM_URL = 'https://YOUR-PUBLIC-CRM-URL/api/google-sheet/leads';
const SYNC_TOKEN = 'PASTE_THE_SAME_TOKEN_AS_.ENV_HERE';
const HEADER_ROW = 2;

function setupGoogleSheetSync() {
  ScriptApp.getProjectTriggers()
    .filter(function(trigger) { return trigger.getHandlerFunction() === 'syncGoogleSheetToCrm'; })
    .forEach(function(trigger) { ScriptApp.deleteTrigger(trigger); });
  ScriptApp.newTrigger('syncGoogleSheetToCrm').timeBased().everyMinutes(5).create();
  syncGoogleSheetToCrm();
}

function syncGoogleSheetToCrm() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const values = sheet.getDataRange().getValues();
  if (values.length <= HEADER_ROW) return;

  const headers = values[HEADER_ROW - 1].map(function(value) {
    return String(value).toLowerCase().replace(/[^a-z0-9]/g, '');
  });
  const index = function(names) {
    for (const name of names) {
      const position = headers.indexOf(name);
      if (position >= 0) return position;
    }
    return -1;
  };
  const columns = {
    date: index(['date']),
    full_name: index(['name', 'fullname']),
    phone: index(['phoneno', 'phone', 'mobile']),
    listing_id: index(['listingid', 'propertyid']),
    property_type: index(['propertytype', 'type']),
    budget: index(['priceofproperty', 'price', 'budget']),
    location: index(['locality', 'location']),
    property_name: index(['project', 'propertyname']),
    source: index(['responsefrom', 'source']),
    notes: index(['sunilremarks', 'remarks', 'notes'])
  };

  const leads = [];
  for (let rowNumber = HEADER_ROW; rowNumber < values.length; rowNumber++) {
    const row = values[rowNumber];
    const value = function(field) {
      const position = columns[field];
      return position >= 0 ? row[position] : '';
    };
    const name = String(value('full_name')).trim();
    const phone = String(value('phone')).trim();
    if (name && phone) {
      leads.push({
        date: value('date') instanceof Date ? value('date').toISOString().slice(0, 10) : String(value('date')),
        full_name: name,
        phone: phone,
        listing_id: String(value('listing_id')).trim(),
        property_type: String(value('property_type')).trim(),
        budget: String(value('budget')).trim(),
        location: String(value('location')).trim(),
        property_name: String(value('property_name')).trim(),
        source: String(value('source')).trim() || '99Acres',
        notes: String(value('notes')).trim()
      });
    }
  }

  for (let start = 0; start < leads.length; start += 100) {
    const response = UrlFetchApp.fetch(CRM_URL, {
      method: 'post',
      contentType: 'application/json',
      headers: { 'X-CRM-Sync-Token': SYNC_TOKEN },
      payload: JSON.stringify(leads.slice(start, start + 100)),
      muteHttpExceptions: true
    });
    if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) {
      throw new Error('CRM sync failed: HTTP ' + response.getResponseCode() + ' ' + response.getContentText());
    }
  }
}
