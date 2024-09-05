from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import pandas as pd
import requests
import os
from datetime import datetime
from io import BytesIO

app = Flask(__name__)
def fetch_data():
    base_url = 'https://erpv14.electrolabgroup.com/'
    endpoint = 'api/resource/Maintenance Schedule'
    url = base_url + endpoint
    limit_per_page = 1000
    start = 0
    all_data = []

    headers = {
        'Authorization': 'token 3ee8d03949516d0:6baa361266cf807'
    }

    params = {
        'fields': '["name","docstatus","naming_series","schedules.service_completion_status","schedules.sales_invoice","schedules.visit_type","schedules.completion_status","schedules.serial_no","schedules.scheduled_date","schedules.customer_schedule_date","customer","schedules.service_report_visit_date","schedules.item_name","schedules.item_name"]',
        'limit_page_length': limit_per_page
    }

    while True:
        params['limit_start'] = start
        response = requests.get(url, params=params, headers=headers)

        if response.status_code == 200:
            data = response.json()
            fetched_data = data.get('data', [])

            if not fetched_data:
                break

            all_data.extend(fetched_data)
            start += limit_per_page

        else:
            print(f"Failed to fetch data. Status code: {response.status_code}")
            return pd.DataFrame()

    return pd.DataFrame(all_data)

def process_data(df, start_date, end_date):
    df['scheduled_date'] = pd.to_datetime(df['scheduled_date'], errors='coerce')
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)
    filtered_df = df[(df['scheduled_date'] >= start_date) & (df['scheduled_date'] <= end_date)]
    filtered_df = filtered_df[filtered_df['sales_invoice'].isnull()]

    allowed_visit_types = [
        'PM Visit 1', 'PM Visit 2', 'PVT Assist Visit',
        'In House Work', 'Others Work', 'ASTM Assist Visit'
    ]
    filtered_df = filtered_df[filtered_df['visit_type'].isin(allowed_visit_types)]
    filtered_df['Sr'] = range(1, len(filtered_df) + 1)
    columns_order = ['Sr'] + [col for col in filtered_df.columns if col != 'Sr']
    filtered_df = filtered_df[columns_order]

    filtered_df.rename(columns={
        'name': 'ID',
        'docstatus': 'Docstatus',
        'naming_series': 'Series',
        'service_completion_status': 'Service Completion Status (Maintenance Schedule Detail)',
        'sales_invoice': 'Sales invoice (Maintenance Schedule Detail)',
        'visit_type': 'Visit Type (Maintenance Schedule Detail)',
        'completion_status': 'Completion Status (Maintenance Schedule Detail)',
        'serial_no': 'Serial No (Maintenance Schedule Detail)',
        'scheduled_date': 'Visit End Date (Maintenance Schedule Detail)',
        'customer_schedule_date': 'Customer Schedule Date (Maintenance Schedule Detail)',
        'customer': 'Customer',
        'service_report_visit_date': 'Service Report Visit Date (Maintenance Schedule Detail)',
        'item_name': 'Item Name (Maintenance Schedule Item)'
    }, inplace=True)

    pm_visit1_completed = filtered_df[
        (filtered_df['Visit Type (Maintenance Schedule Detail)'] == 'PM Visit 1') &
        (filtered_df['Service Completion Status (Maintenance Schedule Detail)'] == 'Completed')
    ]
    pm_visit1_completed = pm_visit1_completed.dropna(subset=['Visit Type (Maintenance Schedule Detail)'])
    names_with_empty_visit_type = filtered_df[filtered_df['Visit Type (Maintenance Schedule Detail)'].isnull()]['ID'].unique()
    pm_visit1_completed = pm_visit1_completed[~pm_visit1_completed['ID'].isin(names_with_empty_visit_type)]

    selected_names = []
    for name in pm_visit1_completed['ID'].unique():
        name_data = pm_visit1_completed[pm_visit1_completed['ID'] == name]
        pm_visit2_data = name_data[name_data['Visit Type (Maintenance Schedule Detail)'] == 'PM Visit 2']

        if len(pm_visit2_data) == 0 or len(pm_visit2_data[pm_visit2_data[
                                                              'Service Completion Status (Maintenance Schedule Detail)'] == 'Completed']) > 0:
            selected_names.append(name)
        elif (pm_visit2_data['Service Completion Status (Maintenance Schedule Detail)'] == 'Completed').all():
            selected_names.append(name)

    selected_names = [
        name for name in selected_names if filtered_df[
            (filtered_df['ID'] == name) & (filtered_df['Visit Type (Maintenance Schedule Detail)'] == 'PM Visit 1')][
            'Service Completion Status (Maintenance Schedule Detail)'].notnull().all()
    ]

    selected_names_df = pd.DataFrame({'Selected Names': selected_names})

    non_pm_visit_df = filtered_df[(filtered_df['Visit Type (Maintenance Schedule Detail)'] != 'PM Visit 1') & (
            filtered_df['Visit Type (Maintenance Schedule Detail)'] != 'PM Visit 2')]

    completed_names = non_pm_visit_df.groupby('ID').filter(
        lambda x: all(x['Service Completion Status (Maintenance Schedule Detail)'] == 'Completed'))

    completed_names = completed_names[['Sr', 'ID']]
    completed_names.drop('Sr', axis=1, inplace=True)

    pm_visit_2_names = filtered_df.groupby('ID').filter(
        lambda x: all(x['Visit Type (Maintenance Schedule Detail)'] == 'PM Visit 2'))
    pm_visit_2_names = pm_visit_2_names.groupby('ID').filter(
        lambda x: all(x['Service Completion Status (Maintenance Schedule Detail)'] == 'Completed'))
    pm_visit_2_names = pm_visit_2_names[['Sr', 'ID']]
    pm_visit_2_names.drop('Sr', axis=1, inplace=True)

    pm_visit_2_names.rename(columns={'ID': 'Selected Names'}, inplace=True)
    completed_names.rename(columns={'ID': 'Selected Names'}, inplace=True)

    concatenated_df = pd.concat(
        [selected_names_df, pm_visit_2_names[['Selected Names']], completed_names[['Selected Names']]],
        ignore_index=True)
    selected_names_df = concatenated_df.drop_duplicates(subset=['Selected Names'])

    return selected_names_df

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']

        if datetime.strptime(start_date, '%Y-%m-%d') > datetime.strptime(end_date, '%Y-%m-%d'):
            flash("End Date must be after Start Date.", 'error')
            return redirect(url_for('index'))

        try:
            df = fetch_data()
            if df.empty:
                flash("No data fetched.", 'info')
                return redirect(url_for('index'))

            selected_names_df = process_data(df, start_date, end_date)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                selected_names_df.to_excel(writer, index=False, sheet_name='Sheet1')
            output.seek(0)
            return send_file(output, download_name='MasterData.xlsx', as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        except Exception as e:
            flash(f"An error occurred: {e}", 'error')
            return redirect(url_for('index'))

    return render_template('index.html')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
