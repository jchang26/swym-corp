import pandas as pd
import numpy as np
from urlparse import urlparse
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import cross_val_score

class Markovify(object):
    def __init__(self, order = 1, subset = 0.0):
        self.order = order
        self.subset = subset
        self.session_columns  = [
            'sessionid',
            'category',
            'imageurl',
            'createddate',
            'pagetitle',
            'pageurl',
            'userid',
            'fullurl',
            'providerid',
            'productid',
            'normalizedpageurl',
            'rawpageurl',
            'referrerurl',
            'rawreferrerurl',
            'utmsource',
            'utmmedium',
            'utmcontent',
            'utmcampaign',
            'utmterm',
            'ipaddress',
            'deviceid',
            'requesttype',
            'eventtype',
            'quantity',
            'price'
        ]
        self.device_columns = [
            'deviceid',
            'devicecategory',
            'devicetype',
            'agenttype',
            'os',
            'osversion',
            'useragent',
            'providerid',
            'createddate',
            'userid',
            'authtype'
        ]
        self.swym_x = None
        self.swym_y = None

        self.referrer_tfidf = None
        self.category_tfidf = None
        self.page_tfidf = None

        #For intermediate testing, remove later
        self.modeling_df = None

    def subset_swym_data(self, data):

        df = data.copy()
        unique_sessions = df['sessionid'].unique()
        train_sess, test_sess = train_test_split(unique_sessions, test_size = self.subset)
        train = df[df['sessionid'].isin(train_sess)]
        test = df[df['sessionid'].isin(test_sess)]

        return test

    def clean_swym_device_data(self, session, device):

        df = device.copy()

        category_list = ['iPhone','Windows PC','Android phone','Mac','iPad','Linux PC'
                        ,'Android PC','Android tablet','Windows phone']
        df['devicecategory'] = df['devicecategory'].apply(lambda x: x if x in category_list else 'Other')

        type_list = ['Smartphone','Personal computer', 'Tablet']
        df['devicetype'] = df['devicetype'].apply(lambda x: x if x in type_list else 'Other')

        agent_list = ['Mobile Browser','Browser']
        df['agenttype'] = df['agenttype'].apply(lambda x: x if x in agent_list else 'Other')

        os_list = ['iOS','Android','Windows','OS X', 'Linux']
        df['os'] = df['os'].apply(lambda x: x if x in os_list else 'Other')

        df.drop(['osversion','useragent','providerid','createddate','authtype']
               , axis = 1, inplace = True)
        df = df[df.notnull()]

        session['key'] = session['userid']+session['deviceid']
        df['key'] = df['userid']+df['deviceid']
        df.drop(['deviceid','userid'], axis = 1, inplace = True)
        df.set_index('key', inplace = True)
        session = session.join(df, on = 'key', how = 'left')
        session.drop('key', axis = 1, inplace = True)
        session['devicecategory'] = session['devicecategory'].fillna('Unknown')
        session['devicetype'] = session['devicetype'].fillna('Unknown')
        session['agenttype'] = session['agenttype'].fillna('Unknown')
        session['os'] = session['os'].fillna('Unknown')

        return session

    def swym_next_action(self, data):

        df = data.copy()
        output_columns = list(df.columns)
        output_columns.append('elapsedtime')
        output_columns.append('totalelapsedtime')
        for o in range(self.order-1):
            col_name = str(o+1)+'prioraction'
            output_columns.append(col_name)
        output_columns.append('nextaction')
        output = pd.DataFrame(columns = output_columns)

        for i in df['sessionid'].unique():
            one_session = df[df['sessionid'] == i].sort_values('createddate')
            elapsedtime = np.zeros(one_session.shape[0],dtype = int)
            totalelapsedtime = np.zeros(one_session.shape[0],dtype = int)
            prioraction_dict = {}
            for o in range(self.order-1):
                prioraction_name = str(o+1)+'prioraction'
                prioraction_dict[prioraction_name] = np.zeros(one_session.shape[0],dtype = int)
            nextaction = np.zeros(one_session.shape[0],dtype = int)
            for j in range(one_session.shape[0]):
                if j > 0:
                    timedelta = one_session['createddate'].iloc[j]-one_session['createddate'].iloc[j-1]
                    totaltimedelta = one_session['createddate'].iloc[j]-one_session['createddate'].iloc[0]
                    elapsedtime[j] = (timedelta/np.timedelta64(1,'s')).astype(int)
                    totalelapsedtime[j] = (totaltimedelta/np.timedelta64(1,'s')).astype(int)
                for o in range(self.order-1):
                    prioraction_name = str(o+1)+'prioraction'
                    if j > o:
                        prioraction_dict[prioraction_name][j] = one_session['eventtype'].iloc[j-o-1]
                if j < one_session.shape[0]-1:
                    nextaction[j] = one_session['eventtype'].iloc[j+1]

            one_session['elapsedtime'] = elapsedtime
            one_session['totalelapsedtime'] = totalelapsedtime
            for o in range(self.order-1):
                col_name = str(o+1)+'prioraction'
                one_session[col_name] = prioraction_dict[col_name]
            one_session['nextaction'] = nextaction

            for o in range(self.order-1):
                col_name = str(o+1)+'prioraction'
                one_session = one_session[one_session[col_name] != 0]
            one_session = one_session[one_session['nextaction'] != 0]
            output = output.append(one_session, ignore_index = True)
        return output

    def swym_featurize(self, data):

        df = data.copy()

        #Dependent Variable
        y = df['nextaction']

        #Create dummy variables for session data
        events_desc = {
            -1: 'Delete from Wishlist',
            1: 'Page View',
            3: 'Add to Cart',
            4: 'Add to Wishlist',
            6: 'Purchase',
            7: 'Remove from Cart',
            8: 'Add to Watchlist',
            104: 'Begin Checkout'
        }
        for i, j in events_desc.items():
            df[j] = df['eventtype'].apply(lambda x: 1 if x == i else 0)
            for o in range(self.order-1):
                event_name = j + ' ' + str(o+1)
                prioraction_name = str(o+1)+'prioraction'
                df[event_name] = df[prioraction_name].apply(lambda x: 1 if x == i else 0)
        for q in range(self.order-1):
            event_name = 'Add to Watchlist '+str(q+1)
            df.drop(event_name, axis = 1, inplace = True)
        df.drop('Add to Watchlist', axis = 1, inplace = True)


        dow_desc = {
            0.0: 'Monday',
            1.0: 'Tuesday',
            2.0: 'Wednesday',
            3.0: 'Thursday',
            4.0: 'Friday',
            5.0: 'Saturday',
            6.0: 'Sunday'
        }
        for i, j in dow_desc.items():
            df[j] = df['dayofweek'].apply(lambda x: 1 if x == i else 0)
        df.drop('Monday', axis = 1, inplace = True)

        hour_desc = {}
        for a in range(24):
            hour_desc[float(a)] = 'Hour '+str(a)
        for i, j in hour_desc.items():
            df[j] = df['hour'].apply(lambda x: 1 if x == i else 0)
        df.drop('Hour 0', axis = 1, inplace = True)

        #Device dummies
        category_list = ['iPhone','Windows PC','Android phone','Mac','iPad','Linux PC'
                        ,'Android PC','Android tablet','Windows phone']
        for a in category_list:
            df[a] = df['devicecategory'].apply(lambda x: 1 if x == a else 0)

        type_list = ['Smartphone','Personal computer', 'Tablet']
        for a in type_list:
            df[a] = df['devicetype'].apply(lambda x: 1 if x == a else 0)

        agent_list = ['Mobile Browser','Browser']
        for a in agent_list:
            df[a] = df['agenttype'].apply(lambda x: 1 if x == a else 0)

        os_list = ['iOS','Android','Windows','OS X', 'Linux']
        for a in os_list:
            df[a] = df['os'].apply(lambda x: 1 if x == a else 0)

        #NLP variables
        self.referrer_tfidf = TfidfVectorizer(stop_words = 'english', max_features = 100)
        self.referrer_tfidf.fit(df['referrerurl'])
        referrer_vect = self.referrer_tfidf.transform(df['referrerurl'])
        referrer_columns = self.referrer_tfidf.get_feature_names()
        referrer_df = pd.DataFrame(referrer_vect.toarray(), columns = referrer_columns)
        df = pd.concat([df,referrer_df], axis = 1)

        self.category_tfidf = TfidfVectorizer(stop_words = 'english', max_features = 100)
        self.category_tfidf.fit(df['category'])
        category_vect = self.category_tfidf.transform(df['category'])
        category_columns = self.category_tfidf.get_feature_names()
        category_df = pd.DataFrame(category_vect.toarray(), columns = category_columns)
        df = pd.concat([df,category_df], axis = 1)

        self.page_tfidf = TfidfVectorizer(stop_words = 'english', max_features = 100)
        self.page_tfidf.fit(df['pagetitle'])
        page_vect = self.page_tfidf.transform(df['pagetitle'])
        page_columns = self.page_tfidf.get_feature_names()
        page_df = pd.DataFrame(page_vect.toarray(), columns = page_columns)
        df = pd.concat([df,page_df], axis = 1)

        #Drop variables
        df.drop(['sessionid','createddate','userid','deviceid','nextaction','providerid','productid'
                ,'referrerurl','category','pagetitle'
                ,'eventtype','dayofweek','hour'
                ,'devicecategory','devicetype','agenttype','os']
                , axis = 1, inplace = True)
        for q in range(self.order-1):
            prioraction_name = str(o+1)+'prioraction'
            df.drop(prioraction_name, axis = 1, inplace = True)

        return df, y

    def swym_prior_history(self, data):

        df = data.copy()
        df['identifier'] = df['sessionid'] + df['userid']
        trunc = df[['sessionid','userid','createddate']]
        trunc = trunc.groupby(['sessionid','userid'], as_index = False).agg({'createddate': 'min'})
        trunc = trunc.sort_values(['userid','sessionid','createddate'])
        prior_hist = np.zeros(trunc.shape[0], dtype = int)
        for row in range(trunc.shape[0]):
            if row > 0:
                if trunc['userid'].iloc[row] == trunc['userid'].iloc[row-1] and trunc['createddate'].iloc[row] > trunc['createddate'].iloc[row-1]:
                    prior_hist[row] = 1
        trunc['hist_ind'] = prior_hist
        trunc['identifier'] = trunc['sessionid'] + trunc['userid']
        trunc.drop(['sessionid','userid','createddate'],axis = 1, inplace = True)
        trunc.set_index('identifier', inplace = True)
        df = df.join(trunc, on = 'identifier', how = 'left')
        df.drop('identifier',axis = 1, inplace = True)
        df['hist_ind'] = df['hist_ind'].fillna(0)
        return df

    def load_swym_data(self, session_path, device_path):

        session = pd.read_csv(session_path, header = None)
        session.columns = self.session_columns
        device = pd.read_csv(device_path, header = None)
        device.columns = self.device_columns

        df = session.copy()
        #df2 = device.copy()

        #Drop unnecessary columns
        df.drop(['imageurl','pageurl','fullurl','normalizedpageurl','rawpageurl','rawreferrerurl'
                ,'utmsource','utmmedium','utmcontent','utmcampaign','utmterm','ipaddress','requesttype']
                ,axis = 1, inplace = True)

        #Drop null sessionid, createddate and eventtype
        #Affect ability to derive predicted variable
        df = df[df['sessionid'].notnull()]
        df = df[df['createddate'].notnull()]
        df = df[df['eventtype'].notnull()]

        #Preliminary feature formatting and engineering
        df['category'] = df['category'].fillna('')
        df['createddate'] = pd.to_datetime(df['createddate'])
        df['dayofweek'] = df['createddate'].dt.dayofweek
        df['hour'] = df['createddate'].dt.hour
        df['pagetitle'] = df['pagetitle'].fillna('')
        df['providerid'] = df['providerid'].fillna('Unknown')
        df['productid'] = df['productid'].fillna(0.0)
        df['referrerurl'] = df['referrerurl'].fillna('')
        df['referrerurl'] = df['referrerurl'].apply(urlparse)
        df['referrerurl'] = df['referrerurl'].apply(lambda x: x.netloc)
        df['deviceid'] = df['deviceid'].fillna('Unknown')
        df['quantity'] = df['quantity'].fillna(0.0)
        df['price'] = df['price'].fillna(0.0)

        print df.shape
        #Join on device data
        df = self.clean_swym_device_data(df, device)
        print df.shape
        df = self.swym_prior_history(df)
        print df.shape
        if self.subset != 0.0:
            df = self.subset_swym_data(df)
        print df.shape
        self.modeling_df = self.swym_next_action(df)
        print df.shape
        self.swym_x, self.swym_y = self.swym_featurize(self.modeling_df)

    def rfc_score(self, x = None, y = None):
        rfc = RandomForestClassifier()
        return np.mean(cross_val_score(rfc,self.swym_x,self.swym_y,cv=5))

    def gbc_score(self, x = None, y = None):
        gbc = GradientBoostingClassifier()
        return np.mean(cross_val_score(gbc,self.swym_x,self.swym_y,cv=5))

if __name__ == '__main__':
    example = Markovify(subset = 0.25)
    example.load_swym_data('data/session_data_training_feb.csv', 'data/devices_data_training_feb.csv')
