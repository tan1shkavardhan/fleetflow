export type Vehicle={id:string;name?:string;vehicle_type?:string;status:string;active:boolean;capacity_kg?:number;max_payload_kg?:number;latitude?:number;longitude?:number;speed?:number;heading?:number;timestamp?:string;movement_classification?:string};
export type Geofence={id:string;name:string;latitude:number;longitude:number;radius_m:number;active:boolean;demo_seed?:boolean};
export type FleetAlert={id?:string;alert_id?:string;vehicle_id:string;type:string;message:string;details?:Record<string,any>;timestamp:string};
export type RecoveryPlan={id:string;delayed_vehicle_id:string;helper_vehicle_id:string;status:string;created_at:string;radius_km:number;plan?:any};
