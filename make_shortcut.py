#!/usr/bin/env python3
"""Generate 'Duo Stock Check' .shortcut (unsigned plist). Sign with:
   shortcuts sign --mode anyone -i DuoStock.shortcut -o DuoStock-signed.shortcut"""
import plistlib, uuid

URL = ("https://www.apple.com/uk/shop/retail/pickup-message?pl=true&mts.0=regular"
       "&parts.0=MK2J4QN/A&parts.1=MK2H4QN/A&location=W1B%205AH")
BUY = "https://www.apple.com/uk/shop/buy-iphone/iphone-duo"

u_fetch, u_match, u_combine, u_replace, u_text = (str(uuid.uuid4()).upper() for _ in range(5))
grp = str(uuid.uuid4()).upper()

def ref(out_uuid, name):
    return {"Value": {"attachmentsByRange": {"{0, 1}": {"OutputUUID": out_uuid, "OutputName": name, "Type": "ActionOutput"}},
                      "string": "￼"}, "WFSerializationType": "WFTextTokenString"}

actions = [
    {"WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
     "WFWorkflowActionParameters": {"UUID": u_fetch, "WFURL": URL, "WFHTTPMethod": "GET",
                                    "ShowHeaders": False, "Advanced": True,
                                    "WFHTTPHeaders": {"Value": {"WFDictionaryFieldValueItems": [
                                        {"WFItemType": 0, "WFKey": {"Value": {"string": "Accept", "attachmentsByRange": {}}, "WFSerializationType": "WFTextTokenString"},
                                         "WFValue": {"Value": {"string": "application/json", "attachmentsByRange": {}}, "WFSerializationType": "WFTextTokenString"}}]},
                                        "WFSerializationType": "WFDictionaryFieldValue"}}},
    {"WFWorkflowActionIdentifier": "is.workflow.actions.text.match",
     "WFWorkflowActionParameters": {"UUID": u_match, "text": ref(u_fetch, "Contents of URL"),
                                    "WFMatchTextPattern": '"storeName":"([^"]+)"[\\s\\S]*?"pickupSearchQuote":"([^"]+)"[\\s\\S]*?"pickupSearchQuote":"([^"]+)"',
                                    "WFMatchTextCaseSensitive": True}},
    {"WFWorkflowActionIdentifier": "is.workflow.actions.text.combine",
     "WFWorkflowActionParameters": {"UUID": u_combine, "text": ref(u_match, "Matches"),
                                    "WFTextSeparator": "Custom", "WFTextCustomSeparator": "\n"}},
    {"WFWorkflowActionIdentifier": "is.workflow.actions.text.replace",
     "WFWorkflowActionParameters": {"UUID": u_replace, "WFInput": ref(u_combine, "Combined Text"),
                                    "WFReplaceTextFind": '"storeName":"([^"]+)"[\\s\\S]*?"pickupSearchQuote":"([^"]+)"[\\s\\S]*?"pickupSearchQuote":"([^"]+)"',
                                    "WFReplaceTextReplace": "$1 — Night Sky: $2 | Star White: $3",
                                    "WFReplaceTextRegularExpression": True, "WFReplaceTextCaseSensitive": True}},
    {"WFWorkflowActionIdentifier": "is.workflow.actions.showresult",
     "WFWorkflowActionParameters": {"Text": ref(u_replace, "Updated Text")}},
    {"WFWorkflowActionIdentifier": "is.workflow.actions.conditional",
     "WFWorkflowActionParameters": {"GroupingIdentifier": grp, "WFControlFlowMode": 0,
                                    "WFInput": {"Type": "Variable", "Variable": ref(u_replace, "Updated Text")},
                                    "WFCondition": 99, "WFConditionalActionString": "vailable"}},
    {"WFWorkflowActionIdentifier": "is.workflow.actions.openurl",
     "WFWorkflowActionParameters": {"WFInput": {"Value": {"string": BUY, "attachmentsByRange": {}}, "WFSerializationType": "WFTextTokenString"}}},
    {"WFWorkflowActionIdentifier": "is.workflow.actions.conditional",
     "WFWorkflowActionParameters": {"GroupingIdentifier": grp, "WFControlFlowMode": 2}},
]

wf = {
    "WFWorkflowName": "Duo Stock Check",
    "WFWorkflowIcon": {"WFWorkflowIconStartColor": 4292311040, "WFWorkflowIconGlyphNumber": 59511},
    "WFWorkflowClientVersion": "2605.0.5",
    "WFWorkflowMinimumClientVersion": 900,
    "WFWorkflowMinimumClientVersionString": "900",
    "WFWorkflowHasShortcutInputVariables": False,
    "WFWorkflowHasOutputFallback": False,
    "WFWorkflowImportQuestions": [],
    "WFWorkflowInputContentItemClasses": [],
    "WFWorkflowTypes": ["WatchKit", "NCWidget", "ActionExtension"],
    "WFWorkflowActions": actions,
}
with open("Duo Stock Check.shortcut", "wb") as f:
    plistlib.dump(wf, f)
print("wrote DuoStock.shortcut")
